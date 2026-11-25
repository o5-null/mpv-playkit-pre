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
:: VS 的 vsscript.dll 默认从包根加载，那样它要靠 %APPDATA%\vapoursynth\vapoursynth.toml
:: 才能找到本包的 python.exe；一旦机器上的 toml 被别的（旧版）vapoursynth 工具重写，
:: 条目格式对不上就直接初始化失败。改成加载包内 Lib\site-packages 下的那份副本：
:: vsscript.dll 往上四层正好是包根，能自己找到 python.exe 与 python3.dll，不碰全局配置。
set "BENCH_VSDL="
if exist "Lib\site-packages\vapoursynth\vsscript.dll" set "BENCH_VSDL=%CD%\Lib\site-packages\vapoursynth\vsscript.dll"

echo ==========================================================
echo == 补帧滤镜性能测试
echo ==   VS 滤镜  ：vapoursynth + portable_config/vs/MEMC_DLSSG_NV.vpy
echo ==   原生滤镜：vf_playkit（D3D11 硬解到 D3D12 零拷贝）
echo == 同一段素材、同一倍数、同一分辨率各跑一遍，
echo == 比较每秒能喂进多少输入帧（等效源 fps）。
echo == 结果会写入 installer\mpv-FilterBench-result.tsv，
echo == 系统/显卡/驱动信息和结果表会汇总进 installer\report.txt
echo ==========================================================

:: ---------------- 1. 测试素材 ----------------
:: 用法（可选，用来跳过交互）：
::   mpv-补帧滤镜跑分.bat ["视频路径"] ["1080p 4k"] [倍数]
:: 不给素材时会自动生成一段 10 秒 1080p 片段并缓存到 %TEMP%。
:: 补帧滤镜只吃硬件帧，合成源没法直接喂滤镜，所以必须先落成文件再硬解。
set "CLIP=%~1"
if defined CLIP goto :clip_ready
for %%f in ("%~dp0bench-clip.mkv" "%~dp0bench-clip.mp4" "%~dp0bench-clip.mov") do if exist "%%~f" set "CLIP=%%~f"
if defined CLIP (
    echo == 使用 installer 目录下的测试素材
    goto :clip_ready
)
echo.
echo == 不需要准备素材：直接回车就会生成一段 10 秒 1080p 测试片段
echo == 也可以把视频拖进本窗口，或粘贴完整路径（自带素材更贴近实际片源）
set /p "CLIP=视频路径（回车=自动生成）: "
if not defined CLIP goto :gen_clip

:clip_ready
set "CLIP=!CLIP:"=!"
if not defined CLIP goto :gen_clip
if not exist "!CLIP!" (
    echo == 找不到文件：!CLIP!
    goto :bye
)
echo == 测试素材：!CLIP!
goto :have_clip

:gen_clip
:: 用 mp4 而不是 mkv：mkv 这里写不出帧率，vpy 会拿 0 去 AssumeFPS 直接失败
set "CLIP=!BENCH_LOGDIR!\bench-src.mp4"
if exist "!CLIP!" (
    echo == 复用上次生成的测试片段（删掉这个文件可重新生成）
    goto :have_clip
)
echo == 正在生成 10 秒 1920x1080 测试片段，只需一次 ...
mpv.com --no-config --o="!CLIP!" --of=mp4 --ovc=libx264 --ovcopts=preset=veryfast,crf=23 --frames=300 "av://lavfi:testsrc2=s=1920x1080:r=30" <nul >nul 2>&1
if not exist "!CLIP!" (
    :: 没有 libx264 的构建退回 NVENC，再不行就让用户手动给素材
    mpv.com --no-config --o="!CLIP!" --of=mp4 --ovc=h264_nvenc --frames=300 "av://lavfi:testsrc2=s=1920x1080:r=30" <nul >nul 2>&1
)
if not exist "!CLIP!" (
    echo == 自动生成失败（这个构建没有可用的 h264 编码器），请手动指定一个视频文件
    goto :bye
)
set "AUTOCLIP=1"
goto :have_clip

:have_clip
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

:: ---------------- 5. 两条路径预检 ----------------
:: 滤镜初始化失败时 mpv 只是禁用滤镜继续播，会跑出一个虚高的假数字。
:: 所以先用 40 帧各试一次，到日志里找“初始化成功”的标记，找不到就跳过该路径。
:: 旧的结果表先删掉，免得中途失败时报告里混进上一次的数字。
del "!BENCH_OUT!" >nul 2>&1
set "SKIP_VS="
set "SKIP_NAT="
echo.
call :precheck VS
call :precheck NATIVE
if defined SKIP_VS if defined SKIP_NAT (
    echo == 两条路径都初始化失败，无法测试（详见 !BENCH_LOGDIR!\pre-*.log）
    goto :report
)

:: ---------------- 6. 逐分辨率跑两条路径 ----------------
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
goto :report

:: ================= 单个路径的预检（40 帧） =================
:precheck
set "PC_TAG=%~1"
set "PC_LOG=!BENCH_LOGDIR!\pre-!PC_TAG!.log"
if /i "!PC_TAG!"=="VS" (
    set "PC_VF=vapoursynth=!BENCH_VS!"
    set "PC_OK=vapoursynth] initialized."
    set "VDLSSG_MULTI=!MULTI!"
    set "VSSCRIPT_PATH=!BENCH_VSDL!"
) else (
    set "PC_VF=playkit=multi=!MULTI!:log=no:dll=!BENCH_DLL!:proxy_dir=!BENCH_PROXY!"
    set "PC_OK=vdlssg bridge ready"
    set "VSSCRIPT_PATH="
)
echo == 预检 !PC_TAG! ...
:: mpv 的日志走 stdout，--log-file 另存一份完整日志（含 debug 级），用它来判断成败
mpv.com --config=no --include=!BENCH_CONF! --log-file="!PC_LOG!" --frames=40 --vf=!PC_VF! "!CLIP!" <nul >nul 2>nul
set "VDLSSG_MULTI="
findstr /i /c:"!PC_OK!" "!PC_LOG!" >nul 2>&1
if errorlevel 1 (
    echo == 警告：!PC_TAG! 滤镜初始化失败，本次跳过（日志 !PC_LOG!）
    if /i "!PC_TAG!"=="VS" set "SKIP_VS=1"
    if /i "!PC_TAG!"=="NATIVE" set "SKIP_NAT=1"
    findstr /i /c:"cannot load" /c:"could not init" /c:"Script evaluation failed" /c:"Disabling filter" "!PC_LOG!" >nul 2>&1 && echo == 原因多半是文件或 DLL 缺失，日志里最后几行带 [e] 的就是原因
)
exit /b

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

if not defined SKIP_VS (
    echo == VS 滤镜 ...
    set "MPV_BENCH_TAG=VS-%~1"
    set "VDLSSG_MULTI=!MULTI!"
    set "VSSCRIPT_PATH=!BENCH_VSDL!"
    mpv.com --config=no --include=!BENCH_CONF! --log-file="!BENCH_LOGDIR!\VS-%~1.log" --vf=d3d11vpp=scale=!SCALE!,vapoursynth=!BENCH_VS! --script=!BENCH_LUA! "!CLIP!" <nul 2>nul
    set "VDLSSG_MULTI="
    set "VSSCRIPT_PATH="
)

if not defined SKIP_NAT (
    echo == 原生滤镜 ...
    set "MPV_BENCH_TAG=NATIVE-%~1"
    set "VSSCRIPT_PATH="
    mpv.com --config=no --include=!BENCH_CONF! --log-file="!BENCH_LOGDIR!\NATIVE-%~1.log" --vf=d3d11vpp=scale=!SCALE!,playkit=multi=!MULTI!:log=no:dll=!BENCH_DLL!:proxy_dir=!BENCH_PROXY! --script=!BENCH_LUA! "!CLIP!" <nul 2>nul
)

set "MPV_BENCH_TAG="
set "MPV_BENCH_OUT="
set "MPV_BENCH_MULTI="
exit /b

:: ================= 生成报告 =================
:report
echo.
echo == 正在收集系统信息（系统 / 显卡 / 驱动 / mpv 版本）并生成报告 ...
set "MPV_BENCH_REPORT=installer\report.txt"
set "MPV_BENCH_TSV=!BENCH_OUT!"
set "MPV_BENCH_CLIP=!CLIP!"
set "MPV_BENCH_SRCW=!SRCW!"
set "MPV_BENCH_RES=!RESSEL!"
set "MPV_BENCH_MULTI=!MULTI!"
set "MPV_BENCH_MPV=%CD%\mpv.com"
if defined AUTOCLIP set "MPV_BENCH_AUTOCLIP=1"
powershell -NoProfile -ExecutionPolicy Bypass -File "installer\mpv_filter_bench_report.ps1" <nul
if exist "installer\report.txt" (
    echo == 报告已生成：installer\report.txt（系统、显卡、驱动版本 + 结果表，可直接发给别人）
) else (
    echo == 报告生成失败（PowerShell 不可用），请手动记录系统信息
)
set "MPV_BENCH_REPORT="
set "MPV_BENCH_TSV="
set "MPV_BENCH_CLIP="
set "MPV_BENCH_SRCW="
set "MPV_BENCH_RES="
set "MPV_BENCH_MULTI="
set "MPV_BENCH_AUTOCLIP="
goto :bye

:bye
echo.
pause
endlocal
