"""按档位包生成 portable_config 的差异部分。

基准 `portable_config/` 是 mpv-lazy 最后发版的配置（本地维护，只有 `shaders/`
跟随上游同步），本模块只做"每个包不一样"的那一点点：

1. 用 `manifests/config.yml` 的预设表重写 `input_uosc.conf` 与 `menu.conf` 里的
   VF 预设区（标记 `# >>> playkit-config:vf` 与 `# <<< playkit-config:vf` 之间）；
2. 用清单的 `native` 段生成 `menu.conf` 的原生滤镜区（标记
   `# >>> playkit-config:native` 与 `# <<< playkit-config:native` 之间，位置在
   VF 滤镜与着色器中间），只有列出的档位包才会出现；
3. 按该包启用的预设裁剪 `portable_config/vs/*.vpy`：没启用的预设，vpy 不进包。

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

# 原生滤镜区（menu.conf 里插在 VF 滤镜与着色器之间）
NATIVE_BEGIN = "# >>> playkit-config:native（由 manifests/config.yml 生成，勿手改）"
NATIVE_END = "# <<< playkit-config:native"

# 通用倍数区（menu.conf 里紧跟在 VF 预设之后，对所有会读 user-data 的插帧生效）
MULTI_BEGIN = "# >>> playkit-config:multi（由 manifests/config.yml 生成，勿手改）"
MULTI_END = "# <<< playkit-config:multi"

# menu.conf 的标记行与禁用项要带状态：select.lua 不认 # 注释，任何一行都会变成
# 菜单项；hidden=true 让它不画，disabled=true 让它画成灰色且点不动。
MENU_HIDDEN = "\thidden=true"

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

    # 预设可以声明自己吃 user-data 的 multi（通用倍数菜单只对这些预设生效）
    for preset in presets:
        if preset.get("multi") not in (None, True):
            common.fail(f"预设 {preset['id']} 的 multi 只能是 true 或省略")

    # 原生滤镜（menu.conf 里的独立段）：条目只能在限定包里出现，且必须给出档位
    native = data.get("native") or {}
    entries = native.get("entries") or []
    seen: set[str] = set()
    for entry in entries:
        for field in ("id", "label", "vf"):
            if not entry.get(field):
                common.fail(f"配置清单的原生滤镜条目缺少 {field}: {entry}")
        eid = entry["id"]
        if eid in seen:
            common.fail(f"配置清单原生滤镜 id 重复: {eid}")
        seen.add(eid)
        multis = entry.get("multi") or []
        if not multis or any(not isinstance(m, int) or m < 2 for m in multis):
            common.fail(f"原生滤镜 {eid} 的 multi 必须是不小于 2 的整数列表")
        if not entry.get("packs"):
            common.fail(f"原生滤镜 {eid} 必须写明 packs（没有档位就永远不会生成）")
        unknown = sorted(set(entry["packs"]) - set(packs))
        if unknown:
            common.fail(f"原生滤镜 {eid} 引用了不存在的包: {', '.join(unknown)}")

    # 通用倍数菜单（可选段）：条目只是倍数，命令全部交给 k7f_multi 落盘并套用
    multi = data.get("multi") or {}
    if multi:
        for field in ("section", "follow_label", "target"):
            if not multi.get(field):
                common.fail(f"配置清单的 multi 段缺少 {field}: {multi}")
        steps = multi.get("entries") or []
        if not steps or any(not isinstance(step, int) or step < 2 for step in steps):
            common.fail("配置清单的 multi.entries 必须是不小于 2 的整数列表")
        if len(set(steps)) != len(steps):
            common.fail("配置清单的 multi.entries 有重复值")
    return data


def pack_config(name: str | None) -> dict:
    data = load()
    key = name or DEFAULT_PACK
    packs = data["packs"]
    if key not in packs:
        available = ", ".join(sorted(packs))
        common.fail(f"配置清单里没有包 {key}（可用: {available}）")
    native = data.get("native") or {}
    entries = [e for e in native.get("entries") or [] if key in e["packs"]]
    multi = data.get("multi") or {}
    # 通用倍数只在"本包启用了会读 user-data 的预设"时才有意义（base 包是 MVTools，
    # 不解析 user-data，生成了也只会是点不动的死选项）
    multi_on = bool(multi) and any(
        p.get("multi") for p in data["presets"] if p["id"] in packs[key].get("enable") or []
    )
    return {
        "name": key,
        "presets": data["presets"],
        "enable": set(packs[key].get("enable") or []),
        "native": native,
        "native_entries": entries,
        "multi": multi,
        "multi_on": multi_on,
    }


# ---------------------------------------------------------------- 生成文本


def _display_width(text: str) -> int:
    """按终端列宽估算（CJK 全角按 2 列），用于 menu.conf 的 tab 对齐。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _vf_command(preset: dict) -> str:
    # 先确保解码器交的是 CPU 帧：用过原生滤镜（hwdec=d3d11va）之后，VS 滤镜
    # 直接吃 D3D11 帧会失败。值没变时 mpv 不会真的重设（m_option_equal 判等），
    # 所以平时这条前缀没有额外代价。
    return f'set hwdec auto-copy; vf set vapoursynth="~~/{preset["vpy"]}"'


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
    """menu.conf 的预设行。

    未启用的预设不能写成 # 注释——select.lua 把每一行都当菜单项，注释会变成
    点不动的空子菜单。改成带 disabled=true 的真条目：看得见、写明缺什么，但灰掉。
    """
    body = []
    for preset in presets:
        enabled = preset["id"] in enable
        label = preset["label"]
        if not enabled:
            label += f"（本包未启用：需 {_reason(preset)}）"
        # 命令列对齐到第 MENU_CMD_COL 列（label 从第 8 列开始）
        gap = MENU_CMD_COL - 8 - _display_width(label)
        tabs = "\t" * max(1, (gap + 7) // 8)
        line = f"\t{label}{tabs}{_vf_command(preset)}"
        body.append(line if enabled else line + "\tdisabled=true")
    return body


def _native_command(entry: dict, multi: int) -> str:
    """原生滤镜的一档命令：先切解码器，再换 vf（顺序不能反）。"""
    params = [f"multi={multi}"]
    for key, value in (entry.get("params") or {}).items():
        params.append(f"{key}={value}")
    vf = ":".join([entry["vf"], *params])
    return f"set hwdec d3d11va; vf set {vf}"


def render_native(native: dict, entries: list[dict]) -> list[str]:
    """menu.conf 的原生滤镜区：段标题 + 清空 + 每个条目一个二级菜单。

    条目为空（该包没装引擎）时整段不生成，标记区之间留空。
    """
    if not entries:
        return []
    body = [native.get("section") or "原生滤镜 (&P)"]
    if native.get("clear_label"):
        body.append(f"\t{native['clear_label']}\t"
                    f"{native.get('clear_command') or 'vf clr playkit'}")
    for entry in entries:
        body.append(f"\t{entry['label']}")
        for multi in entry["multi"]:
            body.append(f"\t\t{multi}× (&{multi})\t{_native_command(entry, multi)}")
    return body


def _multi_command(multi: dict, step: int) -> str:
    """通用倍数菜单的命令：状态与套用都在 k7f_multi 里，菜单只发消息。"""
    return f"script-message-to {multi['target']} set {step}"


def render_multi(multi: dict, enabled: bool) -> list[str]:
    """menu.conf 的通用倍数区：段标题 + 跟随预设 + 每档倍数。

    该包没有会读 user-data 的预设时整段不生成（标记区之间留空）。
    """
    if not enabled:
        return []
    body = [multi["section"]]
    body.append(f"\t{multi['follow_label']}\t"
                f"script-message-to {multi['target']} clear")
    for step in multi["entries"]:
        body.append(f"\t{step}× (&{step})\t{_multi_command(multi, step)}")
    return body


def _read_lines(path: Path) -> tuple[list[str], str]:
    """读文本并按原文件的行尾风格拆分（这两份基准文件是 CRLF）。"""
    raw = path.read_bytes().decode("utf-8")
    eol = "\r\n" if "\r\n" in raw else "\n"
    return raw.replace("\r\n", "\n").split("\n"), eol


def _write_lines(path: Path, lines: list[str], eol: str) -> None:
    path.write_bytes(eol.join(lines).encode("utf-8"))


def splice_block(path: Path, body: list[str], begin_text: str = BEGIN,
                 end_text: str = END) -> None:
    """把标记区之间的内容换成 body；标记缺失即报错（不做猜测式修补）。"""
    if not path.exists():
        common.fail(f"缺少配置文件: {path}")
    lines, eol = _read_lines(path)
    stripped = [ln.strip() for ln in lines]
    try:
        begin = stripped.index(begin_text)
        end = stripped.index(end_text)
    except ValueError:
        common.fail(f"{path.name} 缺少标记区（期望 {begin_text} / {end_text}）")
    if begin > end:
        common.fail(f"{path.name} 的标记区顺序颠倒（{begin_text}）")
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

    # 本地跑过 mpv 之后基准目录里会多出 saved-props.json（save_global_props.lua
    # 写下的运行时状态），它不属于配置，不能跟着进包；_cache/ 的 .keep 占位
    # 目录要保留，缓存内容由 .gitignore 挡在仓库外。
    common.copy_tree(BASE_DIR, _config_root(stage), ignore=["saved-props.json"])
    splice_block(_config_root(stage) / INPUT_NAME, render_input(presets, enable))

    menu = _config_root(stage) / MENU_NAME
    # 标记行本身也要藏起来，否则会变成两个打不开的空菜单
    splice_block(menu, render_menu(presets, enable),
                 BEGIN + MENU_HIDDEN, END + MENU_HIDDEN)
    splice_block(menu, render_native(cfg["native"], cfg["native_entries"]),
                 NATIVE_BEGIN + MENU_HIDDEN, NATIVE_END + MENU_HIDDEN)
    splice_block(menu, render_multi(cfg["multi"], cfg["multi_on"]),
                 MULTI_BEGIN + MENU_HIDDEN, MULTI_END + MENU_HIDDEN)

    keep = {Path(p["vpy"]).name for p in presets if p["id"] in enable}
    removed = prune_vpy(_config_root(stage), keep)
    common.log(f"配置清单: pack={cfg['name']}，启用 {len(keep)} 个预设，"
               f"原生滤镜 {len(cfg['native_entries'])} 项，移除 {removed} 个未启用的 vpy")
    check(stage, pack)


def check(stage: Path, pack: str | None = None) -> None:
    """校验 stage 里的配置确实符合清单（标记、vpy 集合、启用项都存在）。"""
    cfg = pack_config(pack)
    cfg_root = _config_root(stage)
    # input_uosc.conf 是按键表，# 注释安全；menu.conf 由 select.lua 每行都当菜单项
    for name, begin_text, end_text in (
        (INPUT_NAME, BEGIN, END),
        (MENU_NAME, BEGIN + MENU_HIDDEN, END + MENU_HIDDEN),
        (MENU_NAME, NATIVE_BEGIN + MENU_HIDDEN, NATIVE_END + MENU_HIDDEN),
        (MENU_NAME, MULTI_BEGIN + MENU_HIDDEN, MULTI_END + MENU_HIDDEN),
    ):
        path = cfg_root / name
        if not path.exists():
            common.fail(f"stage 缺少 portable_config/{name}")
        lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
        if begin_text not in lines or end_text not in lines:
            common.fail(f"portable_config/{name} 缺少标记区: {begin_text}")

    # 原生滤镜段只在装了引擎的包里出现
    menu_text = (cfg_root / MENU_NAME).read_text(encoding="utf-8")
    section = cfg["native"].get("section") or "原生滤镜 (&P)"
    if cfg["native_entries"] and section not in menu_text:
        common.fail(f"pack={cfg['name']} 缺少原生滤镜段: {section}")
    if not cfg["native_entries"] and section in menu_text:
        common.fail(f"pack={cfg['name']} 不该出现原生滤镜段（没有可用的引擎）")

    # 通用倍数段同理：只有本包启用了会读 user-data 的预设才出现
    multi = cfg["multi"]
    if multi:
        if cfg["multi_on"] and multi["section"] not in menu_text:
            common.fail(f"pack={cfg['name']} 缺少通用倍数段: {multi['section']}")
        if not cfg["multi_on"] and multi["section"] in menu_text:
            common.fail(f"pack={cfg['name']} 不该出现通用倍数段（没有会读 user-data 的预设）")
    for entry in cfg["native_entries"]:
        rel = entry.get("file")
        if not rel:
            continue
        # 中间 stage 可能还没装组件；装了目录却缺文件才算错
        if not (stage / Path(rel).parts[0]).exists():
            continue
        if not (stage / rel).exists():
            common.fail(f"pack={cfg['name']} 的原生滤镜 {entry['id']} 缺少 {rel}")

    keep = {Path(p["vpy"]).name for p in cfg["presets"] if p["id"] in cfg["enable"]}
    vs_dir = cfg_root / VS_REL
    actual = {p.name for p in vs_dir.glob("*.vpy")} if vs_dir.is_dir() else set()
    missing = sorted(keep - actual)
    if missing:
        common.fail(f"pack={cfg['name']} 启用的 vpy 不在包里: " + ", ".join(missing))
    stray = sorted(actual - keep)
    if stray:
        common.fail(f"pack={cfg['name']} 里有多余的 vpy（清单未启用）: " + ", ".join(stray))
