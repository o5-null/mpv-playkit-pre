"""对 stage 与 zip 产物做结构与内容校验。

分层思路：assemble 只保证"该有的在"，verify 再检查"不该有的没有"，
以及 BUILD_INFO / 组件哈希是否与清单一致。
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from . import common

FORBIDDEN_PARTS = ("__pycache__", ".git", ".work")
FORBIDDEN_SUFFIXES = (".pyc", ".pyo", ".part")

# 不应出现在最终包里的开发期文件（官方 embed 包里的头文件/导入库/调试库）
FORBIDDEN_ROOT_NAMES = ("Include", "Libs", "tools", "python3t.dll", "python.cat",
                        "build-details.json", "sdk", "vsgenstubs4", "7z.exe", "get-pip.py")


def check_stage(stage: Path) -> None:
    if not stage.is_dir():
        common.fail(f"stage 目录不存在: {stage}（先跑 python -m build assemble）")
    missing = [rel for rel in (
        "mpv.exe", "mpv.com", "d3dcompiler_43.dll",
        "python.exe", "python3.dll", "portable.vs",
        "vsscript.dll", "libvapoursynth.dll", "vs-plugins",
        "portable_config/mpv.conf", "portable_config/input.conf",
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


def resolve_asset(target: Path) -> Path:
    """--asset 既接受 zip 路径，也接受只含一个 zip 的目录。"""
    if target.is_dir():
        zips = sorted(target.glob("*.zip"))
        if len(zips) != 1:
            common.fail(f"{target} 下应恰好有一个 zip，实际 {len(zips)} 个")
        return zips[0]
    if not target.exists():
        common.fail(f"归档不存在: {target}")
    return target


def check_archive(archive: Path) -> None:
    archive = resolve_asset(archive)
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        roots = {n.split("/")[0] for n in names}
        if len(roots) != 1:
            common.fail(f"压缩包根目录不唯一: {sorted(roots)}")
        root = roots.pop()
        required = ("mpv.exe", "python.exe", "vsscript.dll", "portable_config/mpv.conf",
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
    common.log(f"归档校验通过: {archive.name}")
