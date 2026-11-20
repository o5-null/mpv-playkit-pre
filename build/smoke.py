"""装配后的冒烟测试：确认 Python/VapourSynth/K7sfunc 与本 fork 的扩展真的能跑。

这些检查在 CI 的 windows 运行器上执行，不依赖 GPU：
- python 侧只做 import 与版本打印；
- mpv 侧用 lavfi 生成测试画面，套一个恒等 vpy，验证 VSScript 链路。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import common

FATAL_PATTERNS = (
    "Fatal error",
    "Error parsing option",
    "Failed to load script",
    "Can not load",
    "cannot open shared object",
)
# 无音频设备时的提示不是致命项
NON_FATAL = ("Could not open/initialize audio device",)

PY_CHECK = (
    "import sys, vapoursynth as vs, k7sfunc;"
    "print('python', sys.version.split()[0]);"
    "print('vapoursynth api', vs.R4 if hasattr(vs, 'R4') else 'ok');"
    "print('k7sfunc', k7sfunc.__version__);"
    "print('playkit preset', 'PLAYKIT_RUN' in dir(k7sfunc));"
    "assert hasattr(k7sfunc, 'PLAYKIT_RUN'), 'fork 缺少 mod_playkit';"
    "print('playkit presets', ','.join(k7sfunc.PLAYKIT_PRESETS))"
)

IDENTITY_VPY = """import vapoursynth as vs
core = vs.core
clip = video_in
clip.set_output()
"""

LAVFI_SOURCE = "av://lavfi:testsrc=duration=1:size=320x240:rate=10"

# 冒烟测试会 import k7sfunc，若任由 CPython 写 __pycache__，
# 这些 .pyc 会留在 stage 里被 verify 判为禁止内容。两个手段一起用：
# 环境变量阻止写入，收尾时再兜底清理一遍（mpv 内部加载 vpy 也走同一环境）。
NO_BYTECODE = {"PYTHONDONTWRITEBYTECODE": "1"}


def _clean_bytecode(stage: Path) -> None:
    for cache in stage.rglob("__pycache__"):
        common.remove_tree(cache)


def _report(name: str, proc: subprocess.CompletedProcess) -> None:
    output = (proc.stdout or "") + (proc.stderr or "")
    common.log(f"--- {name} (exit {proc.returncode}) ---")
    for line in output.strip().splitlines()[-12:]:
        common.log("  " + line)


def _fatal(text: str) -> str | None:
    for line in text.splitlines():
        if any(skip in line for skip in NON_FATAL):
            continue
        for pattern in FATAL_PATTERNS:
            if pattern in line:
                return line.strip()
    return None


def smoke(stage: Path) -> None:
    if not stage.exists():
        common.fail(f"stage 不存在: {stage}")

    python = stage / "python.exe"
    mpv = stage / "mpv.exe"

    try:
        # 1) Python / VapourSynth / K7sfunc（含 fork 扩展）
        proc = common.run([python, "-c", PY_CHECK], cwd=stage, timeout=180, env=NO_BYTECODE)
        _report("python imports", proc)
        if proc.returncode != 0:
            common.fail("Python 环境自检失败")

        # 2) mpv 自身
        proc = common.run([mpv, "--version"], cwd=stage, timeout=120, env=NO_BYTECODE)
        _report("mpv --version", proc)
        if proc.returncode != 0 or "mpv v" not in proc.stdout:
            common.fail("mpv --version 失败")

        # 3) VapourSynth 滤镜链路（无配置、恒等 vpy、lavfi 测试源）
        vpy = stage / "smoke_identity.vpy"
        vpy.write_text(IDENTITY_VPY, encoding="utf-8")
        try:
            proc = common.run(
                [mpv, "--no-config", "--vo=null", "--ao=null", "--frames=2",
                 "--vf=vapoursynth=smoke_identity.vpy", LAVFI_SOURCE],
                cwd=stage, timeout=300, env=NO_BYTECODE)
        finally:
            vpy.unlink(missing_ok=True)
        _report("mpv + vf=vapoursynth", proc)
        text = (proc.stdout or "") + (proc.stderr or "")
        problem = _fatal(text)
        if proc.returncode != 0 or problem:
            common.fail(f"vapoursynth 链路测试失败: {problem or 'exit ' + str(proc.returncode)}")
    finally:
        _clean_bytecode(stage)

    common.log("冒烟测试通过")
