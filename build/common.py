"""构建系统共享工具：路径常量、日志、哈希、解包、命令执行。

设计原则（参考 100pangci/mpv_PlayKit_TLS 的分层）：
- manifests/components.yml 只记录"规则"（怎么装、装到哪、许可），不含版本；
- sources.lock.json 记录"钉住的版本"（version/url/sha256/size），由 build.pin 写入；
- 两者在 components() 里合并成完整组件字典，其余模块无感知；
- 所有第三方资产下载后必须通过 SHA-256 二次校验；
- 只支持 windows-x64，因此不引入 PLATFORM_OS 映射。
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "manifests" / "components.yml"
LOCK_PATH = ROOT / "sources.lock.json"
WORK_DIR = ROOT / ".work"
DOWNLOAD_DIR = WORK_DIR / "downloads"
EXTRACT_DIR = WORK_DIR / "extract"
DIST_DIR = ROOT / "dist"
STAGE_ROOT = DIST_DIR / "stage"
OUT_DIR = DIST_DIR / "out"

# 归档内所有时间戳/权限归一化到该时间，保证可复现
FIXED_TIME = (2020, 1, 1, 0, 0, 0)

PLATFORM = "windows-x64"

# 项目名（产物目录、BUILD_INFO、压缩包前缀都用它）；pre = 预览分支，追踪最新版本
PROJECT_NAME = "mpv-playkit-pre"


class BuildError(RuntimeError):
    """构建失败（消息直接面向用户）。"""


def _ensure_utf8_stdout() -> None:
    """把标准输出切到 UTF-8。

    CI 用的 Windows runner 默认 locale 是 en-US，stdout 编码为 cp1252，
    直接 print 中文日志会抛 UnicodeEncodeError。本地中文系统不受影响，
    所以这里只在可重配置时静默切换。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


_ensure_utf8_stdout()


def log(message: str) -> None:
    print(f"[build] {message}", flush=True)


def fail(message: str) -> None:
    raise BuildError(message)


# ---------------------------------------------------------------- manifest

KINDS = {"mpv-7z", "archive", "whl", "file", "git-tree"}
# mpv-7z   : 从 7z 中按 members 取文件，放到包根
# archive  : 解压后按 exclude 过滤整棵树复制到包根（python+VS 环境）
# whl      : 解压到 Lib/site-packages/
# file     : 单文件，下载后放到 target
# git-tree : 仓库 tarball，剥掉顶层目录后按 paths 映射复制（自维护 fork）

LOCK_FIELDS = ("version", "url", "sha256")


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    """读取"规则"清单：只校验结构，不涉及具体版本。"""
    if not path.exists():
        fail(f"清单文件不存在: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != 1:
        fail(f"清单 schema 必须为 1: {path}")
    seen: set[str] = set()
    for comp in data.get("components") or []:
        cid = comp.get("id")
        if not cid:
            fail("组件缺少 id")
        if cid in seen:
            fail(f"组件 id 重复: {cid}")
        seen.add(cid)
        if not comp.get("kind"):
            fail(f"组件 {cid} 缺少字段 kind")
        if comp["kind"] not in KINDS:
            fail(f"组件 {cid} 的 kind 未知: {comp['kind']}")
        if comp["kind"] == "file" and not comp.get("target"):
            fail(f"组件 {cid} (kind=file) 缺少 target")
        if comp["kind"] == "git-tree" and not comp.get("paths"):
            fail(f"组件 {cid} (kind=git-tree) 缺少 paths 映射")
    return data


def load_lock(path: Path = LOCK_PATH) -> dict:
    """读取钉住的版本表；缺失时返回空表（交给 components() 报具体缺失）。"""
    if not path.exists():
        return {"schema": 1, "platform": PLATFORM, "components": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != 1:
        fail(f"lock schema 必须为 1: {path}")
    if not isinstance(data.get("components"), dict):
        fail(f"lock 缺少 components 映射: {path}")
    return data


def save_lock(lock: dict, path: Path = LOCK_PATH) -> None:
    lock["schema"] = 1
    lock["platform"] = PLATFORM
    lock["components"] = dict(sorted((lock.get("components") or {}).items()))
    path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"已写入 {path.name}: {len(lock['components'])} 个组件")


def components(manifest: dict | None = None, lock: dict | None = None) -> list[dict]:
    """规则 + 钉住版本 -> 完整组件列表（按 manifests 中的顺序）。"""
    rules = (manifest or load_manifest()).get("components") or []
    pins = (lock or load_lock()).get("components") or {}
    merged: list[dict] = []
    missing: list[str] = []
    for rule in rules:
        cid = rule["id"]
        pin = pins.get(cid)
        if pin is None:
            if rule.get("disable"):
                merged.append(dict(rule))          # 可选组件允许没有 pin
                continue
            missing.append(cid)
            continue
        absent = [f for f in LOCK_FIELDS if not pin.get(f)]
        if absent:
            fail(f"组件 {cid} 的 lock 条目缺少: {', '.join(absent)}")
        comp = dict(rule)
        comp.update(pin)
        comp["sha256"] = str(comp["sha256"]).lower()
        merged.append(comp)
    if missing:
        fail("sources.lock.json 缺少组件: " + ", ".join(missing)
             + "（用 `python -m build.pin --id <id> --url <url>` 写入）")
    orphans = sorted(set(pins) - {r["id"] for r in rules})
    if orphans:
        fail("sources.lock.json 有清单里不存在的组件: " + ", ".join(orphans))
    return merged


def component(cid: str, manifest: dict | None = None) -> dict:
    for comp in components(manifest):
        if comp["id"] == cid:
            return comp
    fail(f"清单中没有组件: {cid}")


# ---------------------------------------------------------------- 文件工具


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    shutil.copytree(src, dst, dirs_exist_ok=True)


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def match_any(rel: str, patterns: list[str]) -> bool:
    """把 "doc/" 这类前缀写法与通配符统一处理。"""
    for pat in patterns:
        p = pat.replace("\\", "/").rstrip("/")
        if not p:
            continue
        if rel == p or rel.startswith(p + "/"):
            return True
        if fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, p + "/*"):
            return True
    return False


# ---------------------------------------------------------------- 解包


def seven_zip() -> str | None:
    for cand in (
        os.environ.get("SEVEN_Z"),
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
        r"C:\Program Files\7-Zip\7zz.exe",
    ):
        if cand and Path(cand).exists():
            return cand
    for name in ("7z", "7zz", "7za"):
        found = shutil.which(name)
        if found:
            return found
    return None


def extract_7z(archive: Path, dest: Path, members: list[str] | None = None) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    tool = seven_zip()
    if tool:
        cmd = [tool, "x", "-y", f"-o{dest}", str(archive)]
        if members:
            cmd += list(members)
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if proc.returncode != 0:
            fail(f"7z 解包失败 {archive.name}: {proc.stdout[-800:]}{proc.stderr[-400:]}")
        return
    # Windows 10+ 自带 bsdtar，可解 7z/zip
    tar = shutil.which("tar")
    if not tar:
        fail("找不到 7z 或 bsdtar，无法解包 .7z")
    cmd = [tar, "-xf", str(archive), "-C", str(dest)]
    if members:
        cmd += list(members)
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        fail(f"bsdtar 解包失败 {archive.name}: {proc.stdout[-800:]}{proc.stderr[-400:]}")


def extract_zip(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            target = (dest / name).resolve()
            if not str(target).startswith(str(dest.resolve())):
                fail(f"压缩包路径越界: {name}")
        zf.extractall(dest)


def extract_tar(archive: Path, dest: Path) -> None:
    """仓库 tarball；3.12+ 用 filter="data" 防路径穿越与绝对链接。"""
    import tarfile

    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as tf:
        members = [m for m in tf.getmembers() if not m.issym() and not m.islnk()]
        try:
            tf.extractall(dest, members=members, filter="data")
        except TypeError:  # 3.11 及更早没有 filter 参数
            tf.extractall(dest, members=members)


def extract(archive: Path, dest: Path, kind: str, members: list[str] | None = None) -> None:
    if kind in ("tar", "tgz", "tar.gz"):
        extract_tar(archive, dest)
    elif kind == "zip":
        extract_zip(archive, dest)
    else:
        extract_7z(archive, dest, members)


def make_temp_dir(prefix: str) -> Path:
    base = WORK_DIR
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(base)))


# ---------------------------------------------------------------- 进程


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 600,
        env: dict | None = None) -> subprocess.CompletedProcess:
    log("执行: " + " ".join(str(c) for c in cmd))
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        [str(c) for c in cmd], cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, errors="replace", timeout=timeout, env=full_env,
    )


def run_checked(cmd: list[str], cwd: Path | None = None, timeout: int = 600,
                env: dict | None = None) -> subprocess.CompletedProcess:
    proc = run(cmd, cwd=cwd, timeout=timeout, env=env)
    if proc.returncode != 0:
        fail(f"命令失败 (exit {proc.returncode}): {' '.join(map(str, cmd))}\n"
             f"{proc.stdout[-2000:]}\n{proc.stderr[-1000:]}")
    return proc


# ---------------------------------------------------------------- 版本


def git_commit(root: Path = ROOT) -> str:
    git = shutil.which("git") or r"C:\software\Git\cmd\git.exe"
    try:
        proc = subprocess.run([git, "rev-parse", "HEAD"], cwd=str(root),
                              capture_output=True, text=True, errors="replace")
        if proc.returncode == 0:
            return proc.stdout.strip()
    except OSError:
        pass
    return os.environ.get("GITHUB_SHA", "")


def project_version(explicit: str | None = None) -> str:
    """VERSION 文件 + 提交短哈希，例如 2026.11.20-9d5954a。

    显式 --version / PLAYKIT_VERSION 优先；否则 VERSION 文件内容加提交短哈希。
    """
    if explicit:
        return explicit
    env_version = os.environ.get("PLAYKIT_VERSION")
    if env_version:
        return env_version
    ver_file = ROOT / "VERSION"
    base = ver_file.read_text(encoding="utf-8").strip() if ver_file.exists() else ""
    commit = git_commit()
    short = commit[:7] if commit else ""
    if not base:
        return short or "local"
    return f"{base}-{short}" if short else base


def package_basename(version: str) -> str:
    return f"{PROJECT_NAME}-{version}-{PLATFORM}"


def python_exe() -> str:
    return sys.executable
