"""把 stage 打成确定性 zip。

确定性：所有条目的时间戳固定为 2020-01-01、权限固定 0644/0755、条目按路径排序，
同样的 stage 内容两次打包得到相同的字节流。
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from . import common


def _entries(stage: Path):
    for path in sorted(stage.rglob("*")):
        yield path, path.relative_to(stage).as_posix()


def zip_stage(stage: Path, out_dir: Path | None = None,
              version: str | None = None) -> Path:
    out_dir = out_dir or common.OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    version = version or stage.name
    arc_root = common.package_basename(version) if not stage.name.startswith("mpv-playkit-") \
        else stage.name
    target = out_dir / f"{arc_root}.zip"

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path, rel in _entries(stage):
            info = zipfile.ZipInfo(f"{arc_root}/{rel}", date_time=common.FIXED_TIME)
            if path.is_dir():
                info.external_attr = (0o40755 << 16) | 0x10
                info.compress_type = zipfile.ZIP_STORED
                zf.writestr(info, b"")
            else:
                mode = 0o755 if path.suffix.lower() in {".exe", ".com", ".bat"} else 0o644
                info.external_attr = mode << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, path.read_bytes())

    digest = common.sha256_file(target)
    checksum = target.with_suffix(target.suffix + ".sha256")
    checksum.write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    common.log(f"归档完成: {target} ({target.stat().st_size / 1e6:.1f} MB)")
    common.log(f"SHA-256: {digest}")
    return target
