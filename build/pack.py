"""档位包：装配、校验、打包。

档位包有两种形态，由清单里的 `full` 决定：

* **补丁包**（`full` 缺省/false）：只往基础包根追加 `Lib/site-packages/vapoursynth/plugins/`
  与 `vs-plugins/` 之类的东西，产物是**不带顶层目录的覆盖 zip**（`-pack-<name>.zip`）；
* **全量包**（`full: true`）：基础包 + 本档组件装进同一个 stage，产物与基础包同构
  （一个顶层目录的 zip，`...-windows-x64-<name>.zip`），用户只需要下这一个。

目前两个档位（vsdlssg / vs-mlrt）都是全量包，没有补丁包。

失败处理沿用整个构建链的约定：任何不一致都 `common.fail`，不做静默降级。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import common, config, fetch, inputs, package
from .assemble import INSTALLERS, run_post_steps

# 补丁包绝不能带的顶层文件/目录：出现即说明装配串了包，覆盖时会破坏基础包
FORBIDDEN_REL = (
    "mpv.exe",
    "mpv.com",
    "yt-dlp.exe",
    "python.exe",
    "python3.dll",
    "vsscript.dll",
    "libvapoursynth.dll",
    "portable.vs",
    "BUILD_INFO.json",
    # 覆盖 Lib/ 时同样不能碰基础包的 Python 侧本体
    "Lib/site-packages/vapoursynth/__init__.py",
    "Lib/site-packages/vapoursynth/vapoursynth.pyd",
    "Lib/site-packages/vapoursynth/libvapoursynth.dll",
    "Lib/site-packages/vapoursynth/vsscript.dll",
    "Lib/site-packages/k7sfunc",
    "Lib/site-packages/vsmlrt",
)

# 补丁包产物里允许出现的顶层名字（其余一律拒绝，避免把不该覆盖的东西带进去）
# portable_config/ 允许出现：补丁包可以携带与基础包不同的配置，解压即覆盖（这是有意的行为）
ALLOWED_TOP = ("vs-plugins", "Lib", "portable_config", "PACK_INFO.json")


def is_full(name: str) -> bool:
    """全量包：自带基础包内容，产物不需要再叠加到别的包上。"""
    return bool(common.load_pack(name).get("full"))


def pack_basename(name: str, version: str) -> str:
    base = common.package_basename(version)
    return f"{base}-{name}" if is_full(name) else f"{base}-pack-{name}"


def pack_stage(name: str, version: str) -> Path:
    return common.STAGE_ROOT / pack_basename(name, version)


def _short_id(comp: dict) -> str:
    return comp["id"].split("/", 1)[-1]


def select_pack_components(name: str, with_ids: list[str] | None = None,
                           without_ids: list[str] | None = None) -> list[dict]:
    """按补丁包清单取组件，并用 --with/--without 做临时增减（id 可写短名）。"""
    comps = common.pack_components(name)
    known = {_short_id(c) for c in comps}
    for cid in with_ids or []:
        if cid not in known:
            common.fail(f"补丁包 {name} 没有组件: {cid}")
    skip = set(without_ids or [])
    selected = [c for c in comps
                if _short_id(c) not in skip and (not c.get("disable") or _short_id(c) in set(with_ids or []))]
    if not selected:
        common.fail(f"补丁包 {name}: 过滤后没有剩余组件")
    return selected


def _tree_size(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def write_pack_info(stage: Path, name: str, version: str, selected: list[dict],
                    archives: dict[str, Path | None]) -> None:
    """写 PACK_INFO.json：补丁包自己的元信息，不影响基础包的 BUILD_INFO.json。"""
    pack = common.load_pack(name)
    info = {
        "name": name,
        "title": pack.get("title") or name,
        "summary": (pack.get("summary") or "").strip(),
        "full": bool(pack.get("full")),
        "version": version,
        "platform": common.PLATFORM,
        "default": bool(pack.get("default")),
        "base_package": common.package_basename(version),
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "lock_digest": inputs.lock_digest(),
        "components": [
            {
                "id": c["id"],
                "kind": c["kind"],
                "version": c.get("version") or "repo",
                "url": c.get("url"),
                "sha256": c.get("sha256"),
                "size": archives[c["id"]].stat().st_size if archives.get(c["id"]) else None,
            }
            for c in selected
        ],
    }
    (stage / "PACK_INFO.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def verify_pack_stage(stage: Path, selected: list[dict] | None = None,
                      full: bool = False, pack: str | None = None) -> None:
    """stage 侧校验：禁止项、组件声明的 provides、非空。

    full=True 时 stage 就是完整播放器包，基础包的必需项由 verify.check_stage 负责，
    这里只跳过"补丁包不许带本体"与顶层白名单，组件 provides 仍要查。
    """
    if not stage.is_dir():
        common.fail(f"档位包 stage 不存在: {stage}")
    if full:
        from . import verify  # 避免循环导入
        verify.check_stage(stage, pack)
    else:
        for rel in FORBIDDEN_REL:
            if (stage / rel).exists():
                common.fail(f"补丁包不该包含 {rel}（解压覆盖会破坏基础包）")
        for child in stage.iterdir():
            if child.name not in ALLOWED_TOP:
                common.fail(f"补丁包出现未预期的顶层条目: {child.name}")
        # Lib/ 允许放插件目录与 site-packages 里的纯 Python 包（补丁包的运行依赖，如 onnx/numpy），
        # 但不许碰 vapoursynth 本体——那属于基础包。
        plugin_root = "Lib/site-packages/vapoursynth/plugins"
        site_root = "Lib/site-packages"
        stray = []
        for p in (stage / "Lib").rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(stage).as_posix()
            if rel.startswith(plugin_root + "/"):
                continue
            if rel.startswith(site_root + "/") and not rel.startswith(site_root + "/vapoursynth/"):
                continue
            stray.append(rel)
        if stray:
            common.fail("补丁包 Lib/ 下只允许插件目录和 site-packages 的 Python 包，出现了:\n  "
                        + "\n  ".join(stray[:10]))
    missing: list[str] = []
    for comp in selected or []:
        for rel in comp.get("provides") or []:
            if not (stage / rel).exists():
                missing.append(f"{comp['id']}: {rel}")
    if missing:
        common.fail("补丁包缺少组件声明要提供的文件:\n  " + "\n  ".join(missing))
    files = [p for p in stage.rglob("*") if p.is_file()]
    if not files:
        common.fail("补丁包 stage 是空的")


def assemble_pack(name: str, version: str, with_ids: list[str] | None = None,
                  without_ids: list[str] | None = None) -> tuple[Path, list[dict]]:
    """下载并装配档位包 stage（不打包）。全量包先装基础包，再叠本档组件。"""
    from .assemble import assemble

    full = is_full(name)
    selected = select_pack_components(name, with_ids, without_ids)
    common.log(f"装配{'全量包' if full else '补丁包'} {name}（{version}），组件: "
               + ", ".join(c["id"] for c in selected))
    stage = pack_stage(name, version)
    common.remove_tree(stage)
    stage.mkdir(parents=True, exist_ok=True)

    # 全量包：基础包装进同一个 stage（assemble 自己会清目录，所以传 stage 而不是先建）
    # 同时把本档包名交给配置清单，否则基础包会按 base 把本档的 vpy 裁掉。
    if full:
        assemble(version, stage=stage, pack=name)

    archives = fetch.fetch_all(selected)
    for comp in selected:
        INSTALLERS[comp["kind"]](stage, comp, archives[comp["id"]])
        run_post_steps(stage, comp)
    # 本档组件装完后再生成一次：组件也可能带来 vpy（如 k7sfunc 的引擎脚本）
    config.apply(stage, name)
    write_pack_info(stage, name, version, selected, archives)
    verify_pack_stage(stage, selected, full=full, pack=name)
    common.log(f"档位包 stage 完成: {stage} ({_tree_size(stage) / 1e6:.1f} MB)")
    return stage, selected


def build_pack(name: str, version: str, out_dir: Path | None = None,
               with_ids: list[str] | None = None,
               without_ids: list[str] | None = None,
               fmt: str = package.DEFAULT_FORMAT) -> Path:
    """装配 + 打包 + 校验归档，返回产物路径。"""
    from . import verify  # 避免循环导入

    full = is_full(name)
    stage, _ = assemble_pack(name, version, with_ids, without_ids)
    archive = package.package_stage(stage, out_dir=out_dir, flat=not full, fmt=fmt)
    if full:
        verify.check_full_pack_archive(archive)
    else:
        verify.check_pack_archive(archive)
    return archive
