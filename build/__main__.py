"""命令行入口：python -m build <子命令>

    python -m build fetch                 只下载组件
    python -m build assemble              装配 stage
    python -m build smoke                 冒烟测试
    python -m build package               打包 zip（含 .sha256）
    python -m build verify                校验 stage / 归档
    python -m build all                   assemble -> smoke -> package -> verify
    python -m build ci                    等同 CI：fetch -> assemble -> smoke -> package -> verify
    python -m build sync                  同步上游 hooke007/mpv_PlayKit 的着色器目录
    python -m build pack                  构建拓展补丁包（默认全部，或 --name）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import assemble as assemble_mod
from . import common, config as config_mod, fetch, pack as pack_mod, package, smoke, sync as sync_mod, verify

def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--version", help="包版本，默认取 VERSION + 提交短哈希")
    parser.add_argument("--with", dest="with_ids", action="append", default=[],
                        metavar="ID", help="启用清单里 disable 的组件（可重复）")
    parser.add_argument("--without", dest="without_ids", action="append", default=[],
                        metavar="ID", help="跳过某组件（可重复）")
    parser.add_argument("--force", action="store_true", help="忽略下载缓存")
    parser.add_argument("--format", choices=package.FORMATS, default=package.DEFAULT_FORMAT,
                        help="归档格式，默认 7z（最高压缩率）；zip 仅兼容旧流程")


def _stage(args, version: str) -> Path:
    return common.STAGE_ROOT / common.package_basename(version)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m build")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="下载并校验组件")
    _add_common(p_fetch)

    p_asm = sub.add_parser("assemble", help="装配 stage")
    _add_common(p_asm)
    p_asm.add_argument("--pack", help="按该档位包的配置清单生成 portable_config（默认 default）")

    p_cfg = sub.add_parser("config", help="只对已有 stage 重算配置（不下载、不重装）")
    p_cfg.add_argument("--stage", required=True, help="已有 stage 目录")
    p_cfg.add_argument("--pack", help="档位包名（默认 default）")

    p_smoke = sub.add_parser("smoke", help="冒烟测试")
    _add_common(p_smoke)
    p_smoke.add_argument("--stage", nargs="?", const=None,
                         help="stage 目录，默认按版本推导（可只写 --stage）")

    p_pkg = sub.add_parser("package", help="打包归档（默认 7z）")
    _add_common(p_pkg)
    p_pkg.add_argument("--stage", nargs="?", const=None,
                       help="stage 目录，默认按版本推导（可只写 --stage）")
    p_pkg.add_argument("--out-dir")

    p_ver = sub.add_parser("verify", help="校验 stage 或归档")
    _add_common(p_ver)
    p_ver.add_argument("--stage", nargs="?", const=None,
                       help="stage 目录，默认按版本推导（可只写 --stage）")
    p_ver.add_argument("--asset")
    p_ver.add_argument("--pack", nargs="?", const=True, default=None,
                       help="--asset 时按拓展包（overlay 归档）校验；--stage 时可指定档位包名")

    p_all = sub.add_parser("all", help="完整构建")
    _add_common(p_all)
    p_all.add_argument("--out-dir")

    p_ci = sub.add_parser("ci", help="在本地复现 CI 的全流程（fetch 起头）")
    _add_common(p_ci)
    p_ci.add_argument("--out-dir")

    p_sync = sub.add_parser("sync", help="同步上游着色器目录（portable_config/shaders）")
    p_sync.add_argument("--commit", help="指定上游 commit，默认取上游分支最新")
    p_sync.add_argument("--check", action="store_true", help="只检查，有更新时返回 3")

    p_pack = sub.add_parser("pack", help="构建拓展补丁包（overlay 归档）")
    _add_common(p_pack)
    p_pack.add_argument("--name", action="append", default=[], metavar="NAME",
                        help="补丁包名（可重复），默认 manifests/packs/ 下全部")
    p_pack.add_argument("--out-dir")

    args = parser.parse_args(argv)

    # sync 不涉及打包，先处理：它不读 lock、不算版本
    if args.cmd == "sync":
        try:
            return sync_mod.run(args.commit, args.check)
        except common.BuildError as exc:
            print(f"[build] 失败: {exc}", file=sys.stderr, flush=True)
            return 1

    version = common.project_version(getattr(args, "version", None))

    try:
        if args.cmd == "fetch":
            selected = assemble_mod.select_components(args.with_ids, args.without_ids)
            fetch.fetch_all(selected, force=args.force)
            return 0

        if args.cmd == "assemble":
            assemble_mod.assemble(version, args.with_ids, args.without_ids,
                                  pack=args.pack)
            return 0

        if args.cmd == "config":
            config_mod.apply(Path(args.stage), args.pack)
            return 0

        if args.cmd == "smoke":
            smoke.smoke(Path(args.stage) if args.stage else _stage(args, version))
            return 0

        if args.cmd == "package":
            stage = Path(args.stage) if args.stage else _stage(args, version)
            out_dir = Path(args.out_dir) if args.out_dir else common.OUT_DIR
            package.package_stage(stage, out_dir, version, fmt=args.format)
            return 0

        if args.cmd == "verify":
            if args.asset:
                if args.pack:
                    verify.check_pack_archive(Path(args.asset))
                else:
                    verify.check_archive(Path(args.asset))
            else:
                stage = Path(args.stage) if args.stage else _stage(args, version)
                pack = args.pack if isinstance(args.pack, str) else None
                verify.check_stage(stage, pack)
            return 0

        if args.cmd == "pack":
            names = args.name or common.pack_names()
            if not names:
                common.fail("manifests/packs/ 下没有档位包清单")
            out_dir = Path(args.out_dir) if args.out_dir else common.OUT_DIR
            for name in names:
                archive = pack_mod.build_pack(name, version, out_dir,
                                              args.with_ids, args.without_ids,
                                              fmt=args.format)
                common.log(f"档位包完成: {archive}")
            return 0

        if args.cmd == "ci":
            # 与 .github/workflows/build.yml 同序：fetch -> assemble -> smoke -> package -> verify
            selected = assemble_mod.select_components(args.with_ids, args.without_ids)
            fetch.fetch_all(selected, force=args.force)
            stage = assemble_mod.assemble(version, args.with_ids, args.without_ids)
            smoke.smoke(stage)
            out_dir = Path(args.out_dir) if args.out_dir else common.OUT_DIR
            archive = package.package_stage(stage, out_dir, version, fmt=args.format)
            verify.check_stage(stage)
            verify.check_archive(archive)
            common.log(f"CI 复现通过: {archive}")
            return 0

        if args.cmd == "all":
            stage = assemble_mod.assemble(version, args.with_ids, args.without_ids)
            smoke.smoke(stage)
            out_dir = Path(args.out_dir) if args.out_dir else common.OUT_DIR
            archive = package.package_stage(stage, out_dir, version, fmt=args.format)
            verify.check_stage(stage)
            verify.check_archive(archive)
            common.log(f"全部完成: {archive}")
            return 0
    except common.BuildError as exc:
        print(f"[build] 失败: {exc}", file=sys.stderr, flush=True)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
