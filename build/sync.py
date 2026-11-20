"""从上游 hooke007/mpv_PlayKit 同步配置层。

只替换 `portable_config/` 与 `installer/` 两个目录——本项目自己的东西都放在
`overlay/`、`toolkit/`、`build/` 里，因此永远不需要解决合并冲突。

    python -m build.sync                    # 同步上游 main 最新提交
    python -m build.sync --commit <sha>     # 指定提交
    python -m build.sync --check            # 只检查是否有更新
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from . import common, fetch

UPSTREAM_REPO = "hooke007/mpv_PlayKit"
UPSTREAM_URL = f"https://github.com/{UPSTREAM_REPO}.git"
SYNCED_DIRS = ("portable_config", "installer")


def remote_commit(ref: str = "main") -> str:
    proc = common.run(["git", "ls-remote", UPSTREAM_URL, f"refs/heads/{ref}"], timeout=180)
    if proc.returncode != 0 or not proc.stdout.strip():
        common.fail(f"无法获取上游 {ref} 提交: {proc.stderr.strip()}")
    return proc.stdout.split()[0]


def current_commit() -> str | None:
    path = common.ROOT / "upstream.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("commit")
    except json.JSONDecodeError:
        return None


def download_tarball(commit: str) -> Path:
    dest = common.DOWNLOAD_DIR / "upstream" / f"{commit}.tar.gz"
    if dest.exists():
        common.log(f"上游归档已缓存: {dest.name}")
        return dest
    url = f"https://codeload.github.com/{UPSTREAM_REPO}/tar.gz/{commit}"
    fetch._download(url, dest, timeout=600)
    return dest


def replace_from_tarball(tarball: Path, commit: str) -> None:
    tmp = common.make_temp_dir("upstream-")
    try:
        with tarfile.open(tarball, "r:gz") as tf:
            members = [m for m in tf.getmembers() if "/" in m.name]
            if hasattr(tarfile, "data_filter"):
                tf.extractall(tmp, members=members, filter="data")
            else:  # pragma: no cover - 老版本 Python 回退
                tf.extractall(tmp, members=members)
        roots = [p for p in tmp.iterdir() if p.is_dir()]
        if not roots:
            common.fail("上游归档为空")
        src = roots[0]
        for name in SYNCED_DIRS:
            target = common.ROOT / name
            if target.exists():
                common.remove_tree(target)
            src_dir = src / name
            if src_dir.exists():
                common.copy_tree(src_dir, target)
                common.log(f"已替换 {name}/")
            else:
                common.log(f"上游没有 {name}/，跳过")
    finally:
        common.remove_tree(tmp)

    meta = {
        "repository": UPSTREAM_REPO,
        "commit": commit,
        "synced_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "archive_sha256": common.sha256_file(tarball),
    }
    (common.ROOT / "upstream.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(commit_arg: str | None = None, check: bool = False) -> int:
    """返回码约定：0 = 已同步（有变化），3 = 上游无更新，1 = 失败。"""
    commit = commit_arg or remote_commit()
    known = current_commit()
    if check:
        print(f"上游当前: {commit}")
        print(f"仓库记录: {known or '（未同步过）'}")
        return 0 if known == commit else 3
    if known == commit and not commit_arg:
        common.log(f"已是最新上游提交 {commit[:7]}，无需同步")
        return 3
    tarball = download_tarball(commit)
    replace_from_tarball(tarball, commit)
    common.log(f"上游同步完成: {commit[:7]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m build sync")
    parser.add_argument("--commit", help="指定上游提交（默认 main 最新）")
    parser.add_argument("--check", action="store_true", help="只检查是否有更新")
    args = parser.parse_args(argv)

    try:
        return run(args.commit, args.check)
    except common.BuildError as exc:
        print(f"[build] 失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
