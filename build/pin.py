"""组件版本钉住：把新资产的 url/version/sha256 写进 sources.lock.json。

用法
    # 换某个组件的版本（下载 -> 算哈希 -> 写入 lock）
    python -m build.pin --id mpv \
        --url https://github.com/shinchiro/mpv-winbuild-cmake/releases/download/20261201/mpv-x86_64-20261201-git-abcdef0.7z

    # 只算哈希不写文件（先看看）
    python -m build.pin --id k7sfunc --url <url> --dry-run

    # 重新下载全部组件并按 lock 校验（CI 里可当"上游还在不在"的健康检查）
    python -m build.pin --check

    # 列出当前钉住的版本
    python -m build.pin --list
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import common, fetch


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_version(url: str) -> str:
    """没给 --version 时用文件名主干，够用来区分产物。"""
    name = Path(fetch.asset_filename(url)).stem
    for suffix in (".tar",):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name or "unknown"


def measure(url: str, cid: str) -> tuple[str, int]:
    dest = common.DOWNLOAD_DIR / "pin" / f"{cid}-{fetch.asset_filename(url)}"
    try:
        fetch._download(url, dest)
        return common.sha256_file(dest), dest.stat().st_size
    finally:
        dest.unlink(missing_ok=True)


def _rules() -> dict[str, dict]:
    """只读规则清单（不触碰 lock），用于允许"从零开始钉版本"。"""
    return {c["id"]: c for c in (common.load_manifest().get("components") or [])}


def pin(cid: str, url: str, version: str | None, dry_run: bool) -> int:
    if cid not in _rules():
        common.fail(f"清单中没有组件: {cid}")
    digest, size = measure(url, cid)
    version = version or default_version(url)
    print(f"{cid}: {version}")
    print(f"  url    {url}")
    print(f"  sha256 {digest}")
    print(f"  size   {size}")
    if dry_run:
        common.log("--dry-run：未写入 sources.lock.json")
        return 0
    lock = common.load_lock()
    lock.setdefault("components", {})[cid] = {
        "version": version,
        "url": url,
        "sha256": digest,
        "size": size,
        "pinned_at": _now(),
    }
    common.save_lock(lock)
    return 0


def check_all() -> int:
    failed = 0
    for comp in common.components():
        try:
            path = fetch.fetch(comp, force=True)
            common.log(f"OK   {comp['id']} {comp['version']} {path.name}")
        except common.BuildError as exc:
            failed += 1
            common.log(f"FAIL {comp['id']}: {exc}")
    return 1 if failed else 0


def list_pins() -> int:
    """规则与 lock 都直接读，缺 pin 也不报错（方便查看"还差什么"）。"""
    rules = _rules()
    pins = common.load_lock().get("components") or {}
    for cid, rule in rules.items():
        entry = pins.get(cid) or {}
        version = entry.get("version") or "(未钉住)"
        digest = (entry.get("sha256") or "")[:12]
        print(f"{cid:12} {version:38} {digest:12}  {entry.get('url', '')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m build.pin", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--id", help="组件 id")
    parser.add_argument("--url", help="资产直链")
    parser.add_argument("--version", help="版本标签（默认取文件名主干）")
    parser.add_argument("--dry-run", action="store_true", help="只计算，不写 lock")
    parser.add_argument("--check", action="store_true", help="重新下载并校验 lock 内全部组件")
    parser.add_argument("--list", action="store_true", help="列出当前钉住的版本")
    args = parser.parse_args(argv)

    try:
        if args.check:
            return check_all()
        if args.list:
            return list_pins()
        if not (args.id and args.url):
            parser.error("需要 --id 与 --url，或使用 --check / --list")
        return pin(args.id, args.url, args.version, args.dry_run)
    except common.BuildError as exc:
        print(f"[build] 失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
