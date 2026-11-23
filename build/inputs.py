"""构建输入指纹：证明"这个包是由这份源码 + 这份 lock 产出的"。

为什么要它（照抄 100pangci 的做法）：产物里只有一个 version 字符串说明不了
来源。把 build/manifests/lock 等构建输入的逐文件哈希排序后再哈希，
得到一个与机器无关的 inputs_hash，写进 BUILD_INFO.json；同样的 inputs_hash
应该产出同样的包（除 built_at），CI 也能拿它当缓存键。

portable_config/ 的**配置文本**必须进哈希——它已经改为本地维护的基准（mpv-lazy 最后发版），
直接影响包内容；只有 shaders/ 与 fonts/ 这类大件例外（142MB / 14MB），它们分别由
upstream.json 的 commit 和文件本身的来源说明身份。自维护的 K7sfunc fork 由 lock 里的
commit 钉住，不进哈希。configs/ 是包布局文件（portable.vs 等），同样进哈希。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from . import common

INPUT_PATHS: tuple[str, ...] = (
    "build",
    "manifests",
    "sources.lock.json",
    "configs",
    "upstream.json",
    "VERSION",
    "requirements.txt",
    ".github/workflows/build.yml",
    # 本地维护的基准配置：文本部分全部进哈希；shaders/ 由 upstream.json 代表，fonts/ 视为资源
    "portable_config/mpv.conf",
    "portable_config/input_uosc.conf",
    "portable_config/menu.conf",
    "portable_config/profiles.conf",
    "portable_config/script-opts.conf",
    "portable_config/scripts",
    "portable_config/vs",
)

SKIP_DIRS = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def _iter_files() -> list[Path]:
    files: list[Path] = []
    for rel in INPUT_PATHS:
        path = common.ROOT / rel
        if path.is_file():
            files.append(path)
            continue
        if not path.is_dir():
            continue
        for child in sorted(path.rglob("*")):
            if not child.is_file():
                continue
            if any(part in SKIP_DIRS for part in child.parts):
                continue
            if child.suffix in SKIP_SUFFIXES:
                continue
            files.append(child)
    return files


def compute_inputs_hash() -> str:
    """对 "相对路径\\0<sha256>\\n" 排序后求哈希；与遍历顺序无关。"""
    entries = []
    for path in _iter_files():
        rel = path.relative_to(common.ROOT).as_posix()
        entries.append(f"{rel}\0{common.sha256_file(path)}\n")
    entries.sort()
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(entry.encode("utf-8"))
    return digest.hexdigest()


def lock_digest() -> str:
    """单独暴露 lock 的哈希，CI 缓存键只需要它。"""
    if not common.LOCK_PATH.exists():
        return ""
    return common.sha256_file(common.LOCK_PATH)
