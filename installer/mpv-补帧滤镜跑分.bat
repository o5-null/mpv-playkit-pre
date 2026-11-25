:: 说明：本文件为 ANSI（GB18030）编码，用 UTF8 保存会中文乱码
@echo off
chcp 936 >nul
setlocal EnableExtensions EnableDelayedExpansion
title mpv 补帧滤镜跑分（VS 滤镜 vs 原生滤镜）

:: 安装器目录 -> 包根目录（mpv.com / portable_config / vs-plugins 所在的目录）
cd /D "%~dp0.."

set "BENCH_CONF=installer/mpv-FilterBench.conf"
set "BENCH_LUA=installer/mpv_filter_bench.lua"
set "BENCH_OUT=installer\mpv-FilterBench-result.tsv"
set "BENCH_LOGDIR=%TEMP%\mpv-filter-bench"
if not exist "!BENCH_LOGDIR!" mkdir "!BENCH_LOGDIR!" >nul 2>&1
:: vf 的参数里不能写 ~~/（不会被展开），用相对包根目录的路径
set "BENCH_VS=portable_config/vs/MEMC_DLSSG_NV.vpy"
set "BENCH_DLL=vs-plugins/vdlssg.dll"
set "BENCH_PROXY=vs-plugins/dlss45"

echo ==========================================================
echo == 补帧滤镜性能测试
echo ==   VS 滤镜  ：vapoursynth + portable_config/vs/MEMC_DLSSG_NV.vpy
echo ==   原生滤镜：vf_playkit（D3D11 硬解到 D3D12 零拷贝）
echo == 同一段素材、同一倍数、同一分辨率各跑一遍，
echo == 比较每秒能喂进多少输入帧（等效源 fps）。
echo == 结果会写入 installer\mpv-FilterBench-result.tsv
echo ==========================================================

:: ---------------- 1. 测试素材 ----------------
:: 用法（可选，用来跳过交互）：
::   mpv-补帧滤镜跑分.bat "视频路径" "1080p 4k" 2
set "CLIP=%~1"
if defined CLIP goto :clip_ready
for %%f in ("%~dp0bench-clip.mkv" "%~dp0bench-clip.mp4" "%~dp0bench-clip.mov") do if exist "%%~f" set "CLIP=%%~f"
if defined CLIP (
    echo == 使用 installer 目录下的测试素材
    goto :clip_ready
)
echo.
echo == 请把测试用的视频文件拖进本窗口，或直接输入完整路径
echo == 提示：把视频改名为 bench-clip.mkv 放进 installer 目录，以后就不用手动输入
set /p "CLIP=视频路径（回车=退出）: "
if not defined CLIP goto :bye

:clip_ready
set "CLIP=!CLIP:"=!"
if not exist "!CLIP!" (
    echo == 找不到文件：!CLIP!
    goto :bye
)
echo == 测试素材：!CLIP!

:: ---------------- 2. 探测片源宽度 ----------------
echo.
echo == 正在读取片源分辨率 ...
set "PROBE=%TEMP%\mpv-filter-bench-probe.txt"
mpv.com --config=no --vo=null --no-audio --frames=1 --term-playing-msg="BENCHW=${width}" "!CLIP!" <nul >"!PROBE!" 2>&1
set "SRCW="
for /f "tokens=2 delims==" %%a in ('findstr /b "BENCHW=" "!PROBE!"') do set "SRCW=%%a"
del "!PROBE!" >nul 2>&1
if not defined SRCW (
    echo == 读取片源宽度失败，请确认这是 mpv 能打开的视频文件
    goto :bye
)
echo == 片源宽度 !SRCW! px

:: ---------------- 3. 选择分辨率 ----------------
set "RESSEL=%~2"
if defined RESSEL goto :res_ready
echo.
echo == 要测哪些分辨率？
echo ==   1080p = 1920 宽，2k = 2560 宽，4k = 3840 宽
echo ==   可以输入多个（空格或逗号分隔），直接回车 = 全部
set /p "RESSEL=分辨率（回车=全部 1080p 2k 4k）: "

:res_ready
if not defined RESSEL set "RESSEL=1080p 2k 4k"
set "RESSEL=!RESSEL:,= !"
set "RESSEL=!RESSEL:，= !"

:: ---------------- 4. 选择倍数 ----------------
set "MULTI=%~3"
if defined MULTI goto :multi_ready
echo.
echo == 补帧倍数 multi（每对输入帧生成 multi 张），可选 2-6
set /p "MULTI=倍数（回车=2）: "

:multi_ready
if not defined MULTI set "MULTI=2"
echo !MULTI!|findstr /r "^[2-6]$" >nul || set "MULTI=2"
echo == 倍数 !MULTI!

:: ---------------- 5. 逐分辨率跑两条路径 ----------------
> "!BENCH_OUT!" echo tag	WxH	multi	frames	elapsed_s	out_fps	src_fps	note
for %%r in (!RESSEL!) do call :bench_one %%r

echo.
echo ==========================================================
echo == 结果（out_fps = 补帧后每秒呈现帧数，src_fps = 除以倍数后的等效源帧数）
echo ==========================================================
type "!BENCH_OUT!"
echo.
echo == 详细结果已保存：!BENCH_OUT!
echo == 若缺少某一行，运行日志在：!BENCH_LOGDIR!
goto :bye

:: ================= 单个分辨率的测试 =================
:bench_one
set "TW="
if /i "%~1"=="1080p" set "TW=1920"
if /i "%~1"=="1080"  set "TW=1920"
if /i "%~1"=="2k"    set "TW=2560"
if /i "%~1"=="1440p" set "TW=2560"
if /i "%~1"=="1440"  set "TW=2560"
if /i "%~1"=="4k"    set "TW=3840"
if /i "%~1"=="2160p" set "TW=3840"
if /i "%~1"=="2160"  set "TW=3840"
if not defined TW (
    echo == 跳过未知分辨率：%~1（可选 1080p / 2k / 4k）
    exit /b
)

:: 用 d3d11vpp 在硬件域内缩放，倍率按宽度算
set "PSC=%TEMP%\mpv-filter-bench-scale.ps1"
>"!PSC!" echo ([math]::Round(!TW! / !SRCW!, 4)).ToString([Globalization.CultureInfo]::InvariantCulture)
set "SCALE="
for /f "delims=" %%s in ('powershell -NoProfile -ExecutionPolicy Bypass -File "!PSC!"') do set "SCALE=%%s"
del "!PSC!" >nul 2>&1
if not defined SCALE set "SCALE=1"

echo.
echo == ----------------------------------------------------------
echo == 目标宽度 !TW! px，缩放倍率 !SCALE!，倍数 !MULTI!
echo == ----------------------------------------------------------

set "MPV_BENCH_OUT=!BENCH_OUT!"
set "MPV_BENCH_MULTI=!MULTI!"

echo == VS 滤镜 ...
set "MPV_BENCH_TAG=VS-%~1"
set "VDLSSG_MULTI=!MULTI!"
mpv.com --config=no --include=!BENCH_CONF! --vf=d3d11vpp=scale=!SCALE!,vapoursynth=!BENCH_VS! --script=!BENCH_LUA! "!CLIP!" <nul 2>"!BENCH_LOGDIR!\VS-%~1.log"
set "VDLSSG_MULTI="

echo == 原生滤镜 ...
set "MPV_BENCH_TAG=NATIVE-%~1"
mpv.com --config=no --include=!BENCH_CONF! --vf=d3d11vpp=scale=!SCALE!,playkit=multi=!MULTI!:log=no:dll=!BENCH_DLL!:proxy_dir=!BENCH_PROXY! --script=!BENCH_LUA! "!CLIP!" <nul 2>"!BENCH_LOGDIR!\NATIVE-%~1.log"

set "MPV_BENCH_TAG="
set "MPV_BENCH_OUT="
set "MPV_BENCH_MULTI="
exit /b

:bye
echo.
pause
endlocal
