"""把 stage 打成分发包：默认 7z（LZMA2 固实、最高压缩率），zip 保留为兼容退路。

确定性：
- zip：所有条目时间戳固定为 2020-01-01、权限固定 0644/0755、条目按路径排序。
- 7z：不写创建/修改/访问时间（见 sevenzip.SEVENZIP_ARGS），同一版 7-Zip 下重打字节一致。
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from . import common, sevenzip

# 支持的归档格式；默认 7z
FORMATS = ("7z", "zip")
DEFAULT_FORMAT = "7z"


def _entries(stage: Path):
    for path in sorted(stage.rglob("*")):
        yield path, path.relative_to(stage).as_posix()


def _archive_stem(stage: Path, version: str | None, flat: bool) -> str:
    """归档文件名（不含扩展名）。

    flat=True 用于拓展补丁包：条目直接以 `vs-plugins/...` 开头，不带顶层目录，
    这样用户把归档解压到基础包根就是覆盖（Overlay），不需要挪目录。
    """
    if flat:
        return stage.name
    version = version or stage.name
    if stage.name.startswith("mpv-playkit-"):
        return stage.name
    return common.package_basename(version)


def _write_checksum(target: Path, digest: str) -> None:
    checksum = target.with_suffix(target.suffix + ".sha256")
    checksum.write_text(f"{digest}  {target.name}\n", encoding="utf-8")


def zip_stage(stage: Path, out_dir: Path | None = None,
              version: str | None = None, flat: bool = False) -> Path:
    out_dir = out_dir or common.OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    arc_root = "" if flat else _archive_stem(stage, version, flat)
    archive_name = _archive_stem(stage, version, flat)
    target = out_dir / f"{archive_name}.zip"

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        if arc_root:
            arc_info = zipfile.ZipInfo(f"{arc_root}/", date_time=common.FIXED_TIME)
            arc_info.external_attr = (0o40755 << 16) | 0x10
            arc_info.compress_type = zipfile.ZIP_STORED
            zf.writestr(arc_info, b"")
        for path, rel in _entries(stage):
            # 目录条目必须以 "/" 结尾，否则解压工具会把它当 0 字节文件，
            # 后续同类路径就会报 "No such file or directory"。
            name = f"{arc_root}/{rel}" if arc_root else rel
            info = zipfile.ZipInfo(name if not path.is_dir() else name + "/",
                                   date_time=common.FIXED_TIME)
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
    _write_checksum(target, digest)
    common.log(f"归档完成: {target} ({target.stat().st_size / 1e6:.1f} MB)")
    common.log(f"SHA-256: {digest}")
    return target


def sevenzip_stage(stage: Path, out_dir: Path | None = None,
                   version: str | None = None, flat: bool = False) -> Path:
    out_dir = out_dir or common.OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{_archive_stem(stage, version, flat)}.7z"
    common.log(f"7z 打包中（-mx=9 固实，{stage}）...")
    sevenzip.create_archive(stage, target, flat=flat)
    digest = common.sha256_file(target)
    _write_checksum(target, digest)
    common.log(f"归档完成: {target} ({target.stat().st_size / 1e6:.1f} MB)")
    common.log(f"SHA-256: {digest}")
    return target


def package_stage(stage: Path, out_dir: Path | None = None, version: str | None = None,
                  flat: bool = False, fmt: str = DEFAULT_FORMAT) -> Path:
    if fmt == "zip":
        return zip_stage(stage, out_dir=out_dir, version=version, flat=flat)
    if fmt == "7z":
        return sevenzip_stage(stage, out_dir=out_dir, version=version, flat=flat)
    common.fail(f"未知归档格式: {fmt}（支持 {', '.join(FORMATS)}）")
