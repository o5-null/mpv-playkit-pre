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

    # 拓展补丁包：id 写包内短名，键名自动加 "<pack>/" 前缀
    python -m build.pin --pack framegen --id vs-framegen --url <url>
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


def measure(url: str, cid: str, local: str | None = None) -> tuple[str, int]:
    """算 url（或 --file 指定的本地文件）的 sha256 与大小。

    --file 是为"资产还没上传"准备的：先按本地产物算哈希写进 lock，url 仍然是
    将来 release 的直链；上传的必须是同一个文件，否则 CI 校验会失败。
    """
    if local:
        path = Path(local).expanduser().resolve()
        if not path.is_file():
            common.fail(f"--file 指向的文件不存在: {path}")
        return common.sha256_file(path), path.stat().st_size
    dest = common.DOWNLOAD_DIR / "pin" / f"{cid}-{fetch.asset_filename(url)}"
    try:
        fetch._download(url, dest)
        return common.sha256_file(dest), dest.stat().st_size
    finally:
        dest.unlink(missing_ok=True)


def _rules(pack: str | None = None) -> dict[str, dict]:
    """只读规则清单（不触碰 lock），用于允许"从零开始钉版本"。

    pack 给定时读 manifests/packs/<pack>.yml，键名是 "<pack>/<id>"——
    与 components()/pack_components() 的命名空间保持一致。
    """
    if pack:
        rules = common.load_pack(pack).get("components") or []
        return {f"{pack}/{c['id']}": c for c in rules}
    return {c["id"]: c for c in (common.load_manifest().get("components") or [])}


def pin(cid: str, url: str, version: str | None, dry_run: bool,
        pack: str | None = None, local_file: str | None = None) -> int:
    key = f"{pack}/{cid}" if pack and "/" not in cid else cid
    if key not in _rules(pack):
        common.fail(f"清单中没有组件: {key}")
    digest, size = measure(url, key.replace("/", "__"), local_file)
    version = version or default_version(url)
    print(f"{key}: {version}")
    print(f"  url    {url}")
    print(f"  sha256 {digest}")
    print(f"  size   {size}")
    if dry_run:
        common.log("--dry-run：未写入 sources.lock.json")
        return 0
    lock = common.load_lock()
    lock.setdefault("components", {})[key] = {
        "version": version,
        "url": url,
        "sha256": digest,
        "size": size,
        "pinned_at": _now(),
    }
    common.save_lock(lock)
    return 0


def check_all(pack: str | None = None) -> int:
    failed = 0
    targets: list[dict] = []
    if pack:
        targets = common.pack_components(pack)
    else:
        targets = common.components()
        for name in common.pack_names():
            targets.extend(common.pack_components(name))
    for comp in targets:
        try:
            path = fetch.fetch(comp, force=True)
            common.log(f"OK   {comp['id']} {comp['version']} {path.name}")
        except common.BuildError as exc:
            failed += 1
            common.log(f"FAIL {comp['id']}: {exc}")
    return 1 if failed else 0


def list_pins(pack: str | None = None) -> int:
    """规则与 lock 都直接读，缺 pin 也不报错（方便查看"还差什么"）。"""
    pins = common.load_lock().get("components") or {}
    groups: list[tuple[str | None, dict[str, dict]]] = []
    if pack:
        groups.append((pack, _rules(pack)))
    else:
        groups.append((None, _rules()))
        for name in common.pack_names():
            groups.append((name, _rules(name)))
    for group, rules in groups:
        if group:
            print(f"[{group}]")
        for cid, _rule in rules.items():
            entry = pins.get(cid) or {}
            version = entry.get("version") or "(未钉住)"
            digest = (entry.get("sha256") or "")[:12]
            print(f"{cid:24} {version:38} {digest:12}  {entry.get('url', '')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m build.pin", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--id", help="组件 id（配合 --pack 时写包内短名）")
    parser.add_argument("--url", help="资产直链")
    parser.add_argument("--version", help="版本标签（默认取文件名主干）")
    parser.add_argument("--pack", help="拓展补丁包名（manifests/packs/<name>.yml）")
    parser.add_argument("--file", help="用本地文件算哈希（资产尚未上传时用，url 仍写 --url）")
    parser.add_argument("--dry-run", action="store_true", help="只计算，不写 lock")
    parser.add_argument("--check", action="store_true", help="重新下载并校验 lock 内全部组件")
    parser.add_argument("--list", action="store_true", help="列出当前钉住的版本")
    args = parser.parse_args(argv)

    try:
        if args.check:
            return check_all(args.pack)
        if args.list:
            return list_pins(args.pack)
        if not (args.id and args.url):
            parser.error("需要 --id 与 --url，或使用 --check / --list")
        return pin(args.id, args.url, args.version, args.dry_run, args.pack, args.file)
    except common.BuildError as exc:
        print(f"[build] 失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
