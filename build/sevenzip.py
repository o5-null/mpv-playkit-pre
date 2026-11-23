"""7z 归档：定位官方 7-Zip、按固定压缩档出包、列出条目。

输出用 `.7z`（LZMA2 + solid）替代 zip，体积明显更小。为了可追溯，压缩参数写死在这里：
`-mx=7`（七档）、`-ms=on` 固实块；并把创建/修改/访问时间都设为不写入
（`-mtc=off -mtm=off -mta=off`），这样同一份 stage 在同一版 7-Zip 下重复打包字节一致。
字典与匹配参数交给 `-mx=7` 自己决定（不写 `-md`/`-mfb`），否则等于把九档的参数
套回七档，压缩时间省不下来。体积比九档大约多 3~5%，打包耗时降到三分之一左右。

7z 的路径分隔符：7-Zip 的 `l -slt` 在 Windows 上输出反斜杠，这里统一转成正斜杠，
目录条目补结尾 `/`，让 verify 的检查逻辑与 zip 共用。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import common

# 官方 7-Zip 的常见安装位置（winget 装到 Program Files，也有装在 C:\software 的机器）
_CANDIDATES = (
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
    r"C:\software\7-Zip\7z.exe",
)

# 七档压缩 + 固实块 + 不写时间戳（字典/匹配参数交给 -mx=7 决定）
SEVENZIP_ARGS = (
    "-t7z",
    "-mx=7",
    "-m0=lzma2",
    "-ms=on",
    "-mtc=off",
    "-mtm=off",
    "-mta=off",
    "-bd",
    "-y",
)


def _from_registry() -> str | None:
    try:
        import winreg
    except ImportError:  # pragma: no cover - 非 Windows
        return None
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, r"SOFTWARE\7-Zip") as key:
                path, _ = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        exe = Path(path) / "7z.exe"
        if exe.exists():
            return str(exe)
    return None


def find_7z() -> str:
    """按 PLAYKIT_7Z → PATH → 注册表 → 常见安装目录 的顺序找 7z.exe。"""
    env = os.environ.get("PLAYKIT_7Z")
    if env:
        if not Path(env).exists():
            common.fail(f"PLAYKIT_7Z 指向的 7z 不存在: {env}")
        return env
    for name in ("7z", "7za"):
        found = shutil.which(name)
        if found:
            return found
    found = _from_registry()
    if found:
        return found
    for candidate in _CANDIDATES:
        if Path(candidate).exists():
            return candidate
    common.fail("找不到 7z.exe：装 7-Zip（winget install 7zip.7zip）"
                "或用 PLAYKIT_7Z 指定路径")


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, errors="replace")
    if proc.returncode not in (0, 1):  # 1 = 警告（例如某个文件被占用后又成功）
        common.fail(f"7z 失败({proc.returncode}): {' '.join(cmd[:4])} ...\n"
                    f"{proc.stdout[-800:]}{proc.stderr[-800:]}")
    return proc


def create_archive(stage: Path, target: Path, flat: bool = False) -> Path:
    """把 stage 打成 7z。

    flat=True：条目不带顶层目录（补丁包，解压即覆盖）；否则保留 stage 目录名作顶层。
    """
    seven = find_7z()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    if flat:
        cmd = [seven, "a", *SEVENZIP_ARGS, str(target), "."]
        cwd = stage
    else:
        cmd = [seven, "a", *SEVENZIP_ARGS, str(target), stage.name]
        cwd = stage.parent
    _run(cmd, cwd=cwd)
    if not target.exists():
        common.fail(f"7z 没有产出归档: {target}")
    return target


def list_entries(archive: Path) -> list[tuple[str, bool]]:
    """返回 (相对路径, 是否目录)，路径统一成正斜杠、目录补结尾 `/`。"""
    seven = find_7z()
    proc = _run([seven, "l", "-slt", "-ba", str(archive)])
    entries: list[tuple[str, bool]] = []
    block: dict[str, str] = {}

    def flush() -> None:
        path = block.get("Path")
        if path is None:
            return
        is_dir = "D" in block.get("Attributes", "")
        name = path.replace("\\", "/")
        entries.append((name + "/" if is_dir else name, is_dir))

    for line in proc.stdout.splitlines():
        if not line.strip():
            flush()
            block = {}
            continue
        key, sep, value = line.partition(" = ")
        if sep:
            block[key.strip()] = value.strip()
    flush()
    return entries


def list_names(archive: Path) -> list[str]:
    return [name for name, _ in list_entries(archive)]


def read_member(archive: Path, name: str) -> bytes:
    """把单个成员解到内存（verify 读 PACK_INFO.json 用）。"""
    seven = find_7z()
    proc = subprocess.run([seven, "x", "-so", str(archive), name],
                          capture_output=True)
    if proc.returncode not in (0, 1) or not proc.stdout:
        common.fail(f"7z 读取成员失败: {archive.name} :: {name}")
    return proc.stdout
