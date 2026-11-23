"""装配 stage 目录。

装配顺序：先按组件 kind 安装（下载缓存在 .work/downloads），再跑组件声明的
后处理（copies / python_pth），最后铺 portable_config、许可与 BUILD_INFO。

stage 最终布局（相对包根）：
    mpv.exe mpv.com d3dcompiler_43.dll
    yt-dlp.exe
    python.exe pythonw.exe python3.dll pythonXY.dll pythonXY.zip pythonXY._pth
    vsscript.dll libvapoursynth*.dll vsvfw.dll portable.vs vs-plugins/
    Lib/site-packages/{vapoursynth,k7sfunc}/ ...
    portable_config/  licenses/  BUILD_INFO.json
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import common, config, fetch, inputs

# 装配完成后必须存在的路径（相对包根；支持 glob）
REQUIRED_ROOT = (
    "mpv.exe",
    "yt-dlp.exe",
    "portable_config/mpv.conf",
    "portable_config/input_uosc.conf",
    "portable_config/menu.conf",
    "portable_config/scripts",
    "portable_config/scripts/k7f_playkit.lua",
    "portable_config/scripts/k7f_vs.lua",
    "python.exe",
    "python*._pth",
    "python3.dll",
    "vsscript.dll",
    "libvapoursynth.dll",
    "portable.vs",
    "vs-plugins",
    "Lib/site-packages/vapoursynth/__init__.py",
    "Lib/site-packages/k7sfunc/__init__.py",
    "Lib/site-packages/k7sfunc/mod_playkit.py",
    "BUILD_INFO.json",
)


def select_components(with_ids: list[str] | None = None,
                      without_ids: list[str] | None = None) -> list[dict]:
    """按 --with / --without 过滤组件；disable 的组件默认不装。"""
    manifest = common.load_manifest()
    comps = common.components(manifest)
    known = {c["id"] for c in comps}
    for cid in with_ids or []:
        if cid not in known:
            common.fail(f"--with 指定的组件不存在: {cid}")
    with_set = set(with_ids or [])
    without_set = set(without_ids or [])
    selected = []
    for comp in comps:
        cid = comp["id"]
        if cid in without_set:
            continue
        if comp.get("disable") and cid not in with_set:
            continue
        selected.append(comp)
    return selected


# ---------------------------------------------------------------- 各 kind 的安装


def install_mpv(stage: Path, comp: dict, archive: Path) -> None:
    members = comp.get("members") or []
    if not members:
        common.fail(f"{comp['id']}: kind=mpv-7z 需要 members")
    tmp = common.make_temp_dir(f"{comp['id']}-")
    try:
        common.extract_7z(archive, tmp, members)
        for member in members:
            src = tmp / member
            if not src.exists():
                common.fail(f"{comp['id']}: 压缩包内缺少 {member}")
            common.copy_file(src, stage / member)
        common.log(f"{comp['id']}: 取出 {len(members)} 个文件")
    finally:
        # 解包目录不删会一路堆在 .work，每次构建都留一份完整副本
        common.remove_tree(tmp)


def install_archive(stage: Path, comp: dict, archive: Path) -> None:
    install_to = comp.get("install_to", ".")
    dest_root = stage / install_to
    excludes = comp.get("exclude") or []
    # include 非空时只装命中白名单的条目（同一个资产里挑子目录，如只取一颗引擎）
    includes = comp.get("include") or []
    # flatten：把树里的文件按文件名摊平到 install_to（用于 wheel 里的 DLL 集合）
    flatten = bool(comp.get("flatten"))
    tmp = common.make_temp_dir(f"{comp['id']}-")
    try:
        common.extract(archive, tmp, comp.get("extract", "7z"))
        count = 0
        for src in tmp.rglob("*"):
            rel = src.relative_to(tmp).as_posix()
            if includes and not common.match_any(rel, includes):
                continue
            if common.match_any(rel, excludes):
                continue
            target = dest_root / (src.name if flatten else rel)
            if src.is_dir():
                if flatten:
                    continue
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            count += 1
        common.log(f"{comp['id']}: 安装 {count} 个文件 -> {install_to}")
    finally:
        common.remove_tree(tmp)


def install_wheel(stage: Path, comp: dict, archive: Path) -> None:
    """wheel 解压后按 exclude 过滤，避免把 __pycache__ / 头文件 / pdb 带进包里。"""
    install_to = comp.get("install_to", "Lib/site-packages")
    dest_root = stage / install_to
    excludes = comp.get("exclude") or []
    tmp = common.make_temp_dir(f"{comp['id']}-")
    try:
        common.extract_zip(archive, tmp)
        count = 0
        for src in tmp.rglob("*"):
            rel = src.relative_to(tmp).as_posix()
            if common.match_any(rel, excludes):
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


def install_file(stage: Path, comp: dict, archive: Path) -> None:
    target = comp.get("target")
    if not target:
        common.fail(f"{comp['id']}: kind=file 需要 target")
    common.copy_file(archive, stage / target)
    common.log(f"{comp['id']}: -> {target}")


def install_git_tree(stage: Path, comp: dict, archive: Path) -> None:
    tmp = common.make_temp_dir(f"{comp['id']}-")
    try:
        common.extract(archive, tmp, "tar")
        tops = [p for p in tmp.iterdir() if p.is_dir()]
        if len(tops) != 1:
            common.fail(f"{comp['id']}: tarball 顶层目录不是唯一的: {[p.name for p in tops]}")
        root = tops[0]
        for item in comp["paths"]:
            src = root / item["source"]
            if not src.exists():
                common.fail(f"{comp['id']}: 源码树缺少 {item['source']}（fork 是否已推送？）")
            target = stage / item["target"]
            if src.is_dir():
                # 上游 fork 把 __pycache__ 提交进了仓库，复制时一律剔除
                common.copy_tree(src, target, ignore=["__pycache__", "*.pyc"])
            else:
                common.copy_file(src, target)
        common.log(f"{comp['id']}: 复制 {len(comp['paths'])} 条路径")
    finally:
        common.remove_tree(tmp)


def install_repo_files(stage: Path, comp: dict, archive: Path | None) -> None:
    """仓库内文件直接落地（无下载、无版本）。"""
    count = 0
    for item in comp["files"]:
        src = common.ROOT / item["source"]
        if not src.exists():
            common.fail(f"{comp['id']}: 仓库缺少 {item['source']}")
        common.copy_file(src, stage / item["target"])
        count += 1
    common.log(f"{comp['id']}: 落地 {count} 个仓库文件")


INSTALLERS = {
    "mpv-7z": install_mpv,
    "archive": install_archive,
    "whl": install_wheel,
    "file": install_file,
    "git-tree": install_git_tree,
    "repo-files": install_repo_files,
}


# ---------------------------------------------------------------- 后处理


def apply_copies(stage: Path, comp: dict) -> None:
    """组件声明的 copies：把已装好的文件复制到包根（或其它位置）。"""
    for item in comp.get("copies") or []:
        src = stage / item["source"]
        if not src.exists():
            common.fail(f"{comp['id']}: copies 源文件缺失 {item['source']}")
        common.copy_file(src, stage / item["target"])
    if comp.get("copies"):
        common.log(f"{comp['id']}: 复制 {len(comp['copies'])} 个文件到包根")


def configure_python_pth(stage: Path, comp: dict) -> None:
    """改写嵌入式 Python 的 ._pth：加 site-packages，并启用 import site。

    embed 包默认只认 pythonXY.zip 和当前目录，也不执行 import site，
    因此 wheel 装进 Lib/site-packages 后必须显式登记，否则 import vapoursynth 失败。
    """
    pth_files = sorted(stage.glob("python*._pth"))
    if not pth_files:
        common.fail(f"{comp['id']}: 包根没有 python*._pth（embed 包结构变了？）")
    pth = pth_files[0]
    lines = [ln.strip() for ln in pth.read_text(encoding="utf-8-sig").splitlines()]
    wanted = ["Lib\\site-packages", "import site"]
    for line in wanted:
        if not any(ln.lstrip("#").strip().lower() == line.lower() for ln in lines):
            lines.append(line)
    # 原有的 "#import site" 改成启用状态
    lines = ["import site" if ln.lstrip("#").strip().lower() == "import site" else ln
             for ln in lines]
    pth.write_text("\n".join(lines) + "\n", encoding="utf-8")
    common.log(f"{comp['id']}: 已登记 {pth.name} <- Lib\\site-packages")


POST_STEPS = (
    ("copies", apply_copies),
    ("python_pth", configure_python_pth),
)


def run_post_steps(stage: Path, comp: dict) -> None:
    for flag, step in POST_STEPS:
        if comp.get(flag):
            step(stage, comp)


# ---------------------------------------------------------------- 配置与配套文件


def copy_configuration(stage: Path, pack: str | None = None) -> None:
    """铺基准 portable_config，再按配置清单生成该包的差异（预设区 + vpy 裁剪）。"""
    config.apply(stage, pack)


def copy_licenses(stage: Path, selected: list[dict]) -> None:
    dest = stage / "licenses"
    dest.mkdir(parents=True, exist_ok=True)
    common.copy_tree(common.ROOT / "licenses", dest)
    upstream_license = common.ROOT / "LICENSE.MD"
    if upstream_license.exists():
        common.copy_file(upstream_license, dest / "upstream-mpv-playkit-LICENSE.MD")

    # 官方 CPython embed 包自带的许可
    for name in ("LICENSE.txt",):
        src = stage / name
        if src.exists():
            common.copy_file(src, dest / "python-LICENSE.txt")

    # 官方 VapourSynth wheel 的许可（dist-info 里的 COPYING*）
    for entry in stage.glob("Lib/site-packages/vapoursynth-*.dist-info/licenses/*"):
        common.copy_file(entry, dest / f"vapoursynth-{entry.name}")

    rows = ["| 组件 | 版本 | 许可 |", "| --- | --- | --- |"]
    for comp in selected:
        version = comp.get("version") or "仓库内文件"
        rows.append(f"| {comp.get('summary', comp['id'])} | {version} | {comp.get('license', '未标注')} |")
    rows.append("| mpv_PlayKit 配置（portable_config/） | 见 upstream.json | 见上游 LICENSE.MD |")
    (dest / "THIRD_PARTY.md").write_text(
        "# 第三方组件许可\n\n" + "\n".join(rows) + "\n", encoding="utf-8")
    common.log("已写入 licenses/THIRD_PARTY.md")


def write_build_info(stage: Path, version: str, selected: list[dict],
                     archives: dict[str, Path | None]) -> None:
    upstream = {}
    upstream_file = common.ROOT / "upstream.json"
    if upstream_file.exists():
        upstream = json.loads(upstream_file.read_text(encoding="utf-8"))
    components = []
    for comp in selected:
        entry = {
            "id": comp["id"],
            "kind": comp["kind"],
            "summary": comp.get("summary", ""),
            "version": comp.get("version") or "repo",
            "url": comp.get("url"),
            "sha256": (comp.get("sha256") or "").lower() or None,
        }
        archive = archives.get(comp["id"])
        entry["size"] = archive.stat().st_size if archive and archive.exists() else None
        local = fetch.local_override(comp)
        if local is not None and archive and Path(archive).resolve() == local.resolve():
            # 本地覆盖的资产没有经过锁校验，记真实哈希并保留锁里的值供对照
            actual = common.sha256_file(archive)
            if actual != (entry["sha256"] or ""):
                entry["sha256_locked"] = entry["sha256"]
                entry["sha256"] = actual
            entry["overridden"] = True
        components.append(entry)
    info = {
        "name": common.PROJECT_NAME,
        "version": version,
        "platform": common.PLATFORM,
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_commit": common.git_commit(),
        "inputs_hash": inputs.compute_inputs_hash(),
        "lock_digest": inputs.lock_digest(),
        "upstream": upstream,
        "components": components,
    }
    (stage / "BUILD_INFO.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    common.log("已写入 BUILD_INFO.json")


def verify_stage_minimum(stage: Path) -> None:
    missing = []
    for rel in REQUIRED_ROOT:
        if any(ch in rel for ch in "*?"):
            if not any(stage.glob(rel)):
                missing.append(rel)
        elif not (stage / rel).exists():
            missing.append(rel)
    if missing:
        common.fail("stage 缺少必需路径: " + ", ".join(missing))


# ---------------------------------------------------------------- 主流程


def assemble(version: str, with_ids: list[str] | None = None,
             without_ids: list[str] | None = None,
             stage: Path | None = None,
             pack: str | None = None) -> Path:
    selected = select_components(with_ids, without_ids)
    common.log(f"装配 {common.PROJECT_NAME} {version}，组件: "
               + ", ".join(f"{c['id']}={c.get('version') or 'repo'}" for c in selected))
    archives = fetch.fetch_all(selected)

    # stage 可指定：全量档包（pack 的 full: true）把基础包装进自己的 stage，
    # 避免先装一份基础包再整目录复制一遍。
    stage = stage or common.STAGE_ROOT / common.package_basename(version)
    common.remove_tree(stage)
    stage.mkdir(parents=True, exist_ok=True)

    for comp in selected:
        INSTALLERS[comp["kind"]](stage, comp, archives[comp["id"]])
    for comp in selected:
        run_post_steps(stage, comp)

    copy_configuration(stage, pack)
    copy_licenses(stage, selected)
    write_build_info(stage, version, selected, archives)
    verify_stage_minimum(stage)

    size = sum(p.stat().st_size for p in stage.rglob("*") if p.is_file())
    common.log(f"stage 完成: {stage} ({size / 1e6:.1f} MB)")
    return stage
