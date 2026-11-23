"""按档位包生成 portable_config 的差异部分。

基准 `portable_config/` 是 mpv-lazy 最后发版的配置（本地维护，只有 `shaders/`
跟随上游同步），本模块只做"每个包不一样"的那一点点：

1. 用 `manifests/config.yml` 的预设表重写 `input_uosc.conf` 与 `menu.conf` 里的
   VF 预设区（标记 `# >>> playkit-config:vf` 与 `# <<< playkit-config:vf` 之间）；
2. 按该包启用的预设裁剪 `portable_config/vs/*.vpy`：没启用的预设，vpy 不进包。

标记区外的一切保持基准原样，所以改动都集中在清单里，构建出来的包也能一眼看出
"哪些预设可用、哪些为什么不可用"。
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import yaml

from . import common

CONFIG_PATH = common.ROOT / "manifests" / "config.yml"
BASE_DIR = common.ROOT / "portable_config"
DEFAULT_PACK = "base"

BEGIN = "# >>> playkit-config:vf（由 manifests/config.yml 生成，勿手改）"
END = "# <<< playkit-config:vf"

INPUT_NAME = "input_uosc.conf"
MENU_NAME = "menu.conf"
VS_REL = "vs"

# input_uosc.conf 里命令列的起始宽度（沿用基准文件的排版）
INPUT_CMD_COL = 54
# menu.conf 里命令列的目标列（1 个 tab = 8 列）
MENU_CMD_COL = 48


# ---------------------------------------------------------------- 清单


def load(path: Path = CONFIG_PATH) -> dict:
    """读取配置清单并做结构校验（与 components.yml 的 schema 约定一致）。"""
    if not path.exists():
        common.fail(f"配置清单不存在: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != 1:
        common.fail(f"配置清单 schema 必须为 1: {path}")

    presets = data.get("presets") or []
    if not presets:
        common.fail(f"配置清单缺少 presets: {path}")
    ids: set[str] = set()
    keys: set[str] = set()
    vpys: set[str] = set()
    for preset in presets:
        for field in ("id", "key", "vpy", "label"):
            if not preset.get(field):
                common.fail(f"配置清单的预设缺少 {field}: {preset}")
        pid = preset["id"]
        if pid in ids:
            common.fail(f"配置清单预设 id 重复: {pid}")
        ids.add(pid)
        if preset["key"] in keys:
            common.fail(f"配置清单按键重复: {preset['key']}（{pid}）")
        keys.add(preset["key"])
        if preset["vpy"] in vpys:
            common.fail(f"配置清单 vpy 重复: {preset['vpy']}")
        vpys.add(preset["vpy"])

    packs = data.get("packs") or {}
    if DEFAULT_PACK not in packs:
        common.fail(f"配置清单缺少 {DEFAULT_PACK} 包（不带档位的基础 stage）")
    for name, cfg in packs.items():
        unknown = sorted(set(cfg.get("enable") or []) - ids)
        if unknown:
            common.fail(f"配置清单 {name} 包引用了不存在的预设: {', '.join(unknown)}")
    return data


def pack_config(name: str | None) -> dict:
    data = load()
    key = name or DEFAULT_PACK
    packs = data["packs"]
    if key not in packs:
        available = ", ".join(sorted(packs))
        common.fail(f"配置清单里没有包 {key}（可用: {available}）")
    return {"name": key, "presets": data["presets"], "enable": set(packs[key].get("enable") or [])}


# ---------------------------------------------------------------- 生成文本


def _display_width(text: str) -> int:
    """按终端列宽估算（CJK 全角按 2 列），用于 menu.conf 的 tab 对齐。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _vf_command(preset: dict) -> str:
    return f'vf set vapoursynth="~~/{preset["vpy"]}"'


def _reason(preset: dict) -> str:
    return preset.get("requires") or "额外组件"


def render_input(presets: list[dict], enable: set[str]) -> list[str]:
    """input_uosc.conf 的预设行：启用的原样，未启用的整行注释掉并写明原因。"""
    body = []
    for preset in presets:
        command = _vf_command(preset)
        hint = f"VF 滤镜 > {preset['label']}"
        enabled = preset["id"] in enable
        if not enabled:
            hint += f"（本包未启用：需 {_reason(preset)}）"
        pad = " " * max(2, INPUT_CMD_COL - len(command))
        line = f" {preset['key']:<18}{command}{pad}#! {hint}"
        body.append(line if enabled else "#" + line)
    return body


def render_menu(presets: list[dict], enable: set[str]) -> list[str]:
    """menu.conf 的预设行；未启用的写成一行说明，不再给出绑定命令。"""
    body = []
    for preset in presets:
        if preset["id"] not in enable:
            body.append(f"\t# {preset['label']}（本包未启用：需 {_reason(preset)}）")
            continue
        # 命令列对齐到第 MENU_CMD_COL 列（label 从第 8 列开始）
        gap = MENU_CMD_COL - 8 - _display_width(preset["label"])
        tabs = "\t" * max(1, (gap + 7) // 8)
        body.append(f"\t{preset['label']}{tabs}{_vf_command(preset)}")
    return body


def _read_lines(path: Path) -> tuple[list[str], str]:
    """读文本并按原文件的行尾风格拆分（这两份基准文件是 CRLF）。"""
    raw = path.read_bytes().decode("utf-8")
    eol = "\r\n" if "\r\n" in raw else "\n"
    return raw.replace("\r\n", "\n").split("\n"), eol


def _write_lines(path: Path, lines: list[str], eol: str) -> None:
    path.write_bytes(eol.join(lines).encode("utf-8"))


def splice_block(path: Path, body: list[str]) -> None:
    """把标记区之间的内容换成 body；标记缺失即报错（不做猜测式修补）。"""
    if not path.exists():
        common.fail(f"缺少配置文件: {path}")
    lines, eol = _read_lines(path)
    stripped = [ln.strip() for ln in lines]
    try:
        begin = stripped.index(BEGIN)
        end = stripped.index(END)
    except ValueError:
        common.fail(f"{path.name} 缺少 playkit-config 标记区（期望 {BEGIN} / {END}）")
    if begin > end:
        common.fail(f"{path.name} 的 playkit-config 标记区顺序颠倒")
    _write_lines(path, lines[:begin + 1] + body + lines[end:], eol)


# ---------------------------------------------------------------- 应用与校验


def _config_root(stage: Path) -> Path:
    return stage / "portable_config"


def prune_vpy(cfg_root: Path, keep: set[str]) -> int:
    """删掉本包不启用的 .vpy（k7f_bridge.py 之类的非 vpy 文件保留）。"""
    vs_dir = cfg_root / VS_REL
    if not vs_dir.is_dir():
        common.fail(f"portable_config 缺少 {VS_REL}/ 目录")
    removed = 0
    for vpy in sorted(vs_dir.glob("*.vpy")):
        if vpy.name not in keep:
            vpy.unlink()
            removed += 1
    return removed


def apply(stage: Path, pack: str | None = None) -> None:
    """铺基准配置，并按 pack 生成预设区、裁剪 vpy。"""
    if not BASE_DIR.exists():
        common.fail("仓库缺少 portable_config/（打包基准配置）")
    cfg = pack_config(pack)
    presets, enable = cfg["presets"], cfg["enable"]

    common.copy_tree(BASE_DIR, _config_root(stage))
    splice_block(_config_root(stage) / INPUT_NAME, render_input(presets, enable))
    splice_block(_config_root(stage) / MENU_NAME, render_menu(presets, enable))

    keep = {Path(p["vpy"]).name for p in presets if p["id"] in enable}
    removed = prune_vpy(_config_root(stage), keep)
    common.log(f"配置清单: pack={cfg['name']}，启用 {len(keep)} 个预设，"
               f"移除 {removed} 个未启用的 vpy")
    check(stage, pack)


def check(stage: Path, pack: str | None = None) -> None:
    """校验 stage 里的配置确实符合清单（标记、vpy 集合、启用项都存在）。"""
    cfg = pack_config(pack)
    cfg_root = _config_root(stage)
    for name in (INPUT_NAME, MENU_NAME):
        path = cfg_root / name
        if not path.exists():
            common.fail(f"stage 缺少 portable_config/{name}")
        lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
        if BEGIN not in lines or END not in lines:
            common.fail(f"portable_config/{name} 缺少 playkit-config 标记区")

    keep = {Path(p["vpy"]).name for p in cfg["presets"] if p["id"] in cfg["enable"]}
    vs_dir = cfg_root / VS_REL
    actual = {p.name for p in vs_dir.glob("*.vpy")} if vs_dir.is_dir() else set()
    missing = sorted(keep - actual)
    if missing:
        common.fail(f"pack={cfg['name']} 启用的 vpy 不在包里: " + ", ".join(missing))
    stray = sorted(actual - keep)
    if stray:
        common.fail(f"pack={cfg['name']} 里有多余的 vpy（清单未启用）: " + ", ".join(stray))
