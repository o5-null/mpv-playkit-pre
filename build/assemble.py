"""把各组件装配成可分发的便携目录（stage）。

stage 布局（与 mpv-lazy / K7sfunc 文档约定一致）：
    mpv.exe mpv.com d3dcompiler_43.dll
    python.exe ... Lib/ Scripts/            <- 便携 Python + VapourSynth
    VSScript.dll VSVFW.dll VSPipe.exe portable.vs vs-plugins/ vs-scripts/
    Lib/site-packages/k7sfunc/              <- 自维护 fork 的源码树（含 mod_playkit）
    portable_config/                        <- 上游配置 + fork 的前端脚本
    licenses/ BUILD_INFO.json
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import common, fetch, inputs

REQUIRED_ROOT = [
    "mpv.exe",
    "portable_config/mpv.conf",
    "portable_config/scripts",
    "portable_config/scripts/k7f_playkit.lua",
    "python.exe",
    "python*._pth",
    "VSScript.dll",
    "portable.vs",
    "Lib/site-packages/k7sfunc/__init__.py",
    "Lib/site-packages/k7sfunc/mod_playkit.py",
    "BUILD_INFO.json",
]


def select_components(with_ids: list[str], without_ids: list[str]) -> list[dict]:
    manifest = common.load_manifest()
    all_comps = {c["id"]: c for c in common.components(manifest)}
    for cid in with_ids:
        if cid not in all_comps:
            common.fail(f"--with 指定的组件不存在: {cid}")
    selected = []
    for comp in all_comps.values():
        cid = comp["id"]
        if cid in without_ids:
            continue
        if comp.get("disable") and cid not in with_ids:
            common.log(f"跳过未启用的可选组件: {cid}")
            continue
        selected.append(comp)
    return selected


# ---------------------------------------------------------------- 各类组件


def install_mpv(stage: Path, comp: dict, archive: Path) -> None:
    tmp = common.make_temp_dir("mpv-")
    try:
        common.extract_7z(archive, tmp, comp.get("members"))
        for member in comp.get("members") or []:
            src = tmp / member
            if not src.exists():
                common.fail(f"mpv 包内缺少 {member}")
            common.copy_file(src, stage / member)
    finally:
        common.remove_tree(tmp)


def install_archive(stage: Path, comp: dict, archive: Path) -> None:
    tmp = common.make_temp_dir(f"{comp['id']}-")
    install_to = comp.get("install_to", ".")
    dest_root = (stage / install_to).resolve() if install_to != "." else stage.resolve()
    excludes = comp.get("exclude") or []
    try:
        common.extract(archive, tmp, comp.get("extract", "7z"))
        count = 0
        for src in sorted(tmp.rglob("*")):
            rel = src.relative_to(tmp).as_posix()
            if common.match_any(rel, excludes):
                continue
            if src.is_symlink():
                continue
            target = dest_root / rel
            if src.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            count += 1
        common.log(f"{comp['id']}: 安装 {count} 个文件 -> {install_to}")
    finally:
        common.remove_tree(tmp)


def install_wheel(stage: Path, comp: dict, archive: Path) -> None:
    install_to = comp.get("install_to", "Lib/site-packages")
    dest = stage / install_to
    common.extract_zip(archive, dest)
    common.log(f"{comp['id']}: wheel 解包 -> {install_to}")


def install_file(stage: Path, comp: dict, archive: Path) -> None:
    target = comp.get("target")
    if not target:
        common.fail(f"组件 {comp['id']} 缺少 target")
    common.copy_file(archive, stage / target)
    common.log(f"{comp['id']}: 单文件安装 -> {target}")


def install_git_tree(stage: Path, comp: dict, archive: Path) -> None:
    """仓库 tarball：剥掉唯一的顶层目录，再按 paths 逐项复制。"""
    tmp = common.make_temp_dir(f"{comp['id']}-")
    try:
        common.extract(archive, tmp, "tar")
        roots = [p for p in tmp.iterdir() if p.is_dir()]
        if len(roots) != 1:
            common.fail(f"{comp['id']}: 压缩包应当只有一个顶层目录，实际 {len(roots)} 个")
        root = roots[0]
        for item in comp["paths"]:
            src = root / item["source"]
            if not src.exists():
                common.fail(f"{comp['id']}: 源码树缺少 {item['source']}（fork 是否已推送？）")
            dest = stage / item["target"]
            if src.is_dir():
                common.copy_tree(src, dest)
            else:
                common.copy_file(src, dest)
            common.log(f"{comp['id']}: {item['source']} -> {item['target']}")
    finally:
        common.remove_tree(tmp)


INSTALLERS = {
    "mpv-7z": install_mpv,
    "archive": install_archive,
    "whl": install_wheel,
    "file": install_file,
    "git-tree": install_git_tree,
}


# ---------------------------------------------------------------- 本项目内容


def copy_configuration(stage: Path) -> None:
    """上游 portable_config 先铺，再叠加本项目 overlay（同名文件整体覆盖）。"""
    src = common.ROOT / "portable_config"
    if not src.exists():
        common.fail("仓库缺少 portable_config/，请先同步上游")
    common.copy_tree(src, stage / "portable_config")

    overlay = common.ROOT / "overlay"
    if overlay.exists():
        common.copy_tree(overlay, stage)
        common.log("已叠加 overlay/")


def copy_licenses(stage: Path) -> None:
    dest = stage / "licenses"
    dest.mkdir(exist_ok=True)
    repo_licenses = common.ROOT / "licenses"
    if repo_licenses.exists():
        common.copy_tree(repo_licenses, dest)
    readme = common.ROOT / "LICENSE.MD"
    if readme.exists():
        common.copy_file(readme, dest / "upstream-mpv-playkit-LICENSE.MD")

    # 从已安装的运行时里提取随包许可文本（K7sfunc 的许可由 git-tree 组件直接落在 licenses/）
    license_sources = [
        (stage / "LICENSE.txt", "python-vapoursynth-LICENSE.txt"),
    ]
    for src, name in license_sources:
        if src.exists():
            common.copy_file(src, dest / name)

    third_party = [
        "# 第三方组件",
        "",
        "| 组件 | 版本 | 许可 | 来源 |",
        "| --- | --- | --- | --- |",
        "| mpv | shinchiro 构建 | GPL-2.0-or-later / LGPL-2.1-or-later | https://github.com/mpv-player/mpv |",
        "| VapourSynth | R73 | LGPL-2.1-or-later | https://github.com/vapoursynth/vapoursynth |",
        "| CPython | 3.14.3 | PSF-2.0 | https://www.python.org/ |",
        "| K7sfunc | 见 BUILD_INFO.json | GPL-3.0-or-later (src/) | https://github.com/o5-null/K7sfunc |",
        "| mpv_PlayKit 配置 | 见 BUILD_INFO.json | 见 upstream-mpv-playkit-LICENSE.MD | https://github.com/hooke007/mpv_PlayKit |",
        "",
        "mpv 的完整 GPL/LGPL 文本见 mpv 源码仓库的 LICENSE.GPL 与 LICENSE.LGPL。",
    ]
    (dest / "THIRD_PARTY.md").write_text("\n".join(third_party) + "\n", encoding="utf-8")


def write_build_info(stage: Path, version: str, selected: list[dict],
                     archives: dict[str, Path]) -> None:
    upstream_file = common.ROOT / "upstream.json"
    upstream = {}
    if upstream_file.exists():
        upstream = json.loads(upstream_file.read_text(encoding="utf-8"))

    info = {
        "name": common.PROJECT_NAME,
        "version": version,
        "platform": common.PLATFORM,
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_commit": common.git_commit(),
        "inputs_hash": inputs.compute_inputs_hash(),
        "lock_digest": inputs.lock_digest(),
        "upstream": upstream,
        "components": [
            {
                "id": comp["id"],
                "kind": comp["kind"],
                "version": comp["version"],
                "url": comp["url"],
                "sha256": comp["sha256"].lower(),
                "size": archives[comp["id"]].stat().st_size if comp["id"] in archives else None,
            }
            for comp in selected
        ],
    }
    (stage / "BUILD_INFO.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def verify_stage_minimum(stage: Path) -> None:
    missing = []
    for rel in REQUIRED_ROOT:
        if "*" in rel:
            if not any(stage.glob(rel)):
                missing.append(rel)
        elif not (stage / rel).exists():
            missing.append(rel)
    if missing:
        common.fail("stage 缺少必需内容: " + ", ".join(missing))


# ---------------------------------------------------------------- 入口


def assemble(version: str, with_ids: list[str] | None = None,
             without_ids: list[str] | None = None) -> Path:
    with_ids = with_ids or []
    without_ids = without_ids or []
    selected = select_components(with_ids, without_ids)

    common.log(f"装配 {common.PROJECT_NAME} {version}，组件: {', '.join(c['id'] for c in selected)}")
    archives = fetch.fetch_all(selected)

    stage = common.STAGE_ROOT / common.package_basename(version)
    common.remove_tree(stage)
    stage.mkdir(parents=True)

    for comp in selected:
        INSTALLERS[comp["kind"]](stage, comp, archives[comp["id"]])

    copy_configuration(stage)
    copy_licenses(stage)
    write_build_info(stage, version, selected, archives)
    verify_stage_minimum(stage)

    size = sum(p.stat().st_size for p in stage.rglob("*") if p.is_file())
    common.log(f"stage 完成: {stage} ({size / 1e6:.1f} MB)")
    return stage
