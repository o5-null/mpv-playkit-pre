"""对 stage 与归档产物（7z / zip）做结构与内容校验。

分层思路：assemble 只保证"该有的在"，verify 再检查"不该有的没有"，
以及 BUILD_INFO / 组件哈希是否与清单一致。
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from . import common, config, sevenzip

ARCHIVE_SUFFIXES = (".7z", ".zip")

FORBIDDEN_PARTS = ("__pycache__", ".git", ".work")
FORBIDDEN_SUFFIXES = (".pyc", ".pyo", ".part")

# 不应出现在最终包里的开发期文件（官方 embed 包里的头文件/导入库/调试库）
FORBIDDEN_ROOT_NAMES = ("Include", "Libs", "tools", "python3t.dll", "python.cat",
                        "build-details.json", "sdk", "vsgenstubs4", "7z.exe", "get-pip.py")


def check_stage(stage: Path, pack: str | None = None) -> None:
    if not stage.is_dir():
        common.fail(f"stage 目录不存在: {stage}（先跑 python -m build assemble）")
    missing = [rel for rel in (
        "mpv.exe", "mpv.com",
        "yt-dlp.exe",
        "python.exe", "python3.dll", "portable.vs",
        "vsscript.dll", "libvapoursynth.dll", "vs-plugins",
        "portable_config/mpv.conf",
        # 基准配置（mpv-lazy 最后发版）自带的几份入口文件
        "portable_config/input_uosc.conf",
        "portable_config/menu.conf",
        "portable_config/script-opts.conf",
        "portable_config/scripts/input_plus.lua",
        "portable_config/scripts/uosc/main.lua",
        "portable_config/scripts/k7f_playkit.lua",
        "portable_config/scripts/k7f_vs.lua",
        "portable_config/script-opts/k7f_playkit.conf",
        "Lib/site-packages/vapoursynth/__init__.py",
        "Lib/site-packages/k7sfunc/__init__.py",
        "Lib/site-packages/k7sfunc/mod_playkit.py",
        "licenses/THIRD_PARTY.md",
        "BUILD_INFO.json",
    ) if not (stage / rel).exists()]
    if missing:
        common.fail("stage 校验失败，缺少: " + ", ".join(missing))

    for path in stage.rglob("*"):
        rel = path.relative_to(stage).as_posix()
        if any(part in rel.split("/") for part in FORBIDDEN_PARTS):
            common.fail(f"stage 含禁止目录: {rel}")
        if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES:
            common.fail(f"stage 含禁止文件类型: {rel}")

    for name in FORBIDDEN_ROOT_NAMES:
        if (stage / name).exists():
            common.fail(f"stage 含多余内容: {name}")

    info = json.loads((stage / "BUILD_INFO.json").read_text(encoding="utf-8"))
    if not info.get("components"):
        common.fail("BUILD_INFO.json 中没有组件记录")
    if info.get("platform") != common.PLATFORM:
        common.fail(f"BUILD_INFO.json 平台字段异常: {info.get('platform')}")
    for key in ("inputs_hash", "lock_digest"):
        if not info.get(key):
            common.fail(f"BUILD_INFO.json 缺少 {key}（产物无法追溯）")

    # 配置清单：标记区、启用的 vpy 与实际的 vs/ 内容必须一致
    config.check(stage, pack)


def _check_dir_entries(names: list[str]) -> None:
    """目录条目必须以 "/" 结尾，否则标准解压工具会把它当 0 字节文件建出来，
    之后同名前缀下的文件必然报 "No such file or directory"。"""
    dirs = set()
    for name in names:
        if name.endswith("/"):
            dirs.add(name)
            continue
        parts = name.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]) + "/")
    missing_dirs = sorted(d for d in dirs if d not in set(names))
    if missing_dirs:
        common.fail("压缩包目录条目缺少结尾斜杠: " + ", ".join(missing_dirs[:5]))


def list_names(archive: Path) -> list[str]:
    """归档内的条目名；7z 与 zip 统一（目录以 "/" 结尾）。"""
    if archive.suffix.lower() == ".7z":
        return sevenzip.list_names(archive)
    with zipfile.ZipFile(archive) as zf:
        return zf.namelist()


def read_member(archive: Path, name: str) -> bytes:
    if archive.suffix.lower() == ".7z":
        return sevenzip.read_member(archive, name)
    with zipfile.ZipFile(archive) as zf:
        return zf.read(name)


def resolve_asset(target: Path) -> Path:
    """--asset 既接受归档路径，也接受只含一个归档的目录。"""
    if target.is_dir():
        found = sorted(p for p in target.iterdir()
                       if p.suffix.lower() in ARCHIVE_SUFFIXES)
        if len(found) != 1:
            common.fail(f"{target} 下应恰好有一个 7z/zip，实际 {len(found)} 个")
        return found[0]
    if not target.exists():
        common.fail(f"归档不存在: {target}")
    return target


def check_archive(archive: Path) -> None:
    archive = resolve_asset(archive)
    names = list_names(archive)
    roots = {n.split("/")[0] for n in names}
    if len(roots) != 1:
        common.fail(f"压缩包根目录不唯一: {sorted(roots)}")
    root = roots.pop()
    required = ("mpv.exe", "yt-dlp.exe", "python.exe", "vsscript.dll", "portable_config/mpv.conf",
                "BUILD_INFO.json",
                "Lib/site-packages/vapoursynth/__init__.py",
                "Lib/site-packages/k7sfunc/__init__.py",
                "Lib/site-packages/k7sfunc/mod_playkit.py",
                "portable_config/scripts/k7f_playkit.lua",
                "portable_config/scripts/k7f_vs.lua")
    for rel in required:
        if f"{root}/{rel}" not in names:
            common.fail(f"压缩包缺少: {root}/{rel}")
    for name in names:
        if any(part in name.split("/") for part in FORBIDDEN_PARTS):
            common.fail(f"压缩包含禁止目录: {name}")

    # 目录条目必须以 "/" 结尾：否则标准解压工具会把它当 0 字节文件建出来，
    # 之后同名前缀下的文件必然报 "No such file or directory"。
    _check_dir_entries(names)
    common.log(f"归档校验通过: {archive.name}")


def check_full_pack_archive(archive: Path) -> None:
    """全量档包产物校验：与基础包同构（唯一顶层目录）+ 本档自己的 PACK_INFO.json。"""
    archive = resolve_asset(archive)
    names = list_names(archive)
    roots = {n.split("/")[0] for n in names}
    if len(roots) != 1:
        common.fail(f"压缩包根目录不唯一: {sorted(roots)}")
    root = roots.pop()
    required = ("PACK_INFO.json", "mpv.exe", "python.exe", "vsscript.dll",
                "portable_config/mpv.conf", "BUILD_INFO.json",
                "Lib/site-packages/vapoursynth/__init__.py",
                "Lib/site-packages/k7sfunc/__init__.py")
    for rel in required:
        if f"{root}/{rel}" not in names:
            common.fail(f"全量档包缺少: {root}/{rel}")
    for name in names:
        if any(part in name.split("/") for part in FORBIDDEN_PARTS):
            common.fail(f"压缩包含禁止目录: {name}")
    _check_dir_entries(names)
    info = json.loads(read_member(archive, f"{root}/PACK_INFO.json").decode("utf-8"))
    if not info.get("full"):
        common.fail("PACK_INFO.json 没有标记 full: true（全量档包）")
    common.log(f"全量档包校验通过: {archive.name}")


def check_pack_archive(archive: Path) -> None:
    """补丁包产物校验：无顶层目录、只含 vs-plugins/、Lib/ 插件与 PACK_INFO.json。

    全量档包（`full: true`）与基础包同构，有一个顶层目录——自动转到
    check_full_pack_archive，这样 `build verify --pack --asset` 对两种形态都通用。
    """
    archive = resolve_asset(archive)
    names = list_names(archive)
    tops = {n.split("/")[0] for n in names}
    if len(tops) == 1 and tops.pop() not in ("vs-plugins", "Lib", "portable_config", "PACK_INFO.json"):
        return check_full_pack_archive(archive)
    if not names:
        common.fail(f"补丁包是空的: {archive.name}")
    plugin_root = "Lib/site-packages/vapoursynth/plugins/"
    site_root = "Lib/site-packages/"
    for name in names:
        top = name.split("/")[0]
        if top not in ("vs-plugins", "Lib", "portable_config", "PACK_INFO.json"):
            common.fail(f"补丁包出现未预期的顶层条目: {name}")
        if name.startswith("Lib/"):
            rel = name.rstrip("/")
            if not (rel.startswith(plugin_root.rstrip("/") + "/")
                    or plugin_root.rstrip("/").startswith(rel)
                    or (rel.startswith(site_root) and not rel.startswith(site_root + "vapoursynth"))):
                common.fail(f"补丁包的 Lib/ 下只允许插件目录与 Python 包: {name}")
        if any(part in name.split("/") for part in FORBIDDEN_PARTS):
            common.fail(f"补丁包含禁止目录: {name}")
    # 具体组件校验交给 manifests/packs/*.yml 的 provides，
    # 这里只确认"确实装了东西"和"没有串包"。
    files = [n for n in names if not n.endswith("/")]
    if not any(n.startswith("vs-plugins/") or n.startswith(plugin_root)
               or n.startswith("portable_config/") for n in files):
        common.fail("补丁包没有往 vs-plugins/、插件目录或 portable_config/ 放任何文件")
    _check_dir_entries(names)
    common.log(f"补丁包校验通过: {archive.name}")
