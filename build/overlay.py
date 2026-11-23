"""本地配置覆盖。

上游 `portable_config/` 是整目录同步的，不能直接放自定义文件；本仓库自己的
覆盖放在 `overlay/`，按包根结构镜像。同步/装配后把 overlay 叠上去，并在
`portable_config/mpv.conf` 末尾补一行 include，用来加载 `playkit-preset.conf`。

只做两件事：
1. `copy_tree(overlay, root)`；
2. 若 `root/portable_config/mpv.conf` 还没有 include 行，就追加。
"""

from __future__ import annotations

from pathlib import Path

from . import common

INCLUDE_LINE = 'include = "~~/playkit-preset.conf"'
INCLUDE_MARKER = "# PlayKit local overlay (managed by build/overlay.py)"


def _ensure_include(root: Path) -> None:
    target = root / "portable_config" / "mpv.conf"
    if not target.exists():
        return
    data = target.read_bytes()
    needle = INCLUDE_LINE.encode("utf-8")
    if needle in data:
        return
    suffix = b"" if data.endswith(b"\n") else b"\n"
    block = (
        suffix
        + INCLUDE_MARKER.encode("utf-8")
        + b"\n"
        + needle
        + b"\n"
    )
    target.write_bytes(data + block)
    common.log("已写入 playkit-preset include")


def apply(root: Path) -> None:
    """把仓库 overlay/ 叠到 root（工作树或 stage）。"""
    overlay = common.ROOT / "overlay"
    if not overlay.exists():
        return
    common.copy_tree(overlay, root)
    _ensure_include(root)
    common.log("已应用 overlay/（本地配置覆盖）")
