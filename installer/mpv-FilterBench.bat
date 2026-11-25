:: mpv frame-interpolation filter benchmark
:: Compares VS filters (vapoursynth + MEMC_*.vpy) with the native playkit filter.
:: Lanes: VS-DLSSG (vdlssg), VS-VFG (vvfg), NATIVE (playkit + vdlssg).
:: This file is intentionally plain ASCII: cmd.exe misreads UTF-8 batch files.
@echo off
setlocal EnableExtensions EnableDelayedExpansion
title mpv filter benchmark (VS filters vs native filter)

:: installer dir -> package root (where mpv.com / portable_config / vs-plugins live)
cd /D "%~dp0.."

set "BENCH_CONF=installer/mpv-FilterBench.conf"
set "BENCH_LUA=installer/mpv_filter_bench.lua"
set "BENCH_OUT=installer\mpv-FilterBench-result.tsv"
set "BENCH_LOGDIR=%TEMP%\mpv-filter-bench"
if not exist "!BENCH_LOGDIR!" mkdir "!BENCH_LOGDIR!" >nul 2>&1
:: --vf does not expand ~~/, so all paths are relative to the package root
set "BENCH_VS_DLSSG=portable_config/vs/MEMC_DLSSG_NV.vpy"
set "BENCH_VS_VFG=portable_config/vs/MEMC_VFG_NV.vpy"
set "BENCH_DLL=vs-plugins/vdlssg.dll"
set "BENCH_PROXY=vs-plugins/dlss45"
:: VS loads vsscript.dll from the package root by default, which needs the global
:: %APPDATA%\vapoursynth\vapoursynth.toml to locate this package's python.exe.
:: If another (older) vapoursynth tool rewrites that toml, VS init fails. Use the
:: copy under Lib\site-packages instead: four levels up from vsscript.dll is the
:: package root, so it finds python.exe / python3.dll on its own.
set "BENCH_VSDL="
if exist "Lib\site-packages\vapoursynth\vsscript.dll" set "BENCH_VSDL=%CD%\Lib\site-packages\vapoursynth\vsscript.dll"

echo ==========================================================
echo == Frame-interpolation filter benchmark
echo ==   VS-DLSSG : vapoursynth + MEMC_DLSSG_NV.vpy (vdlssg / DLSS-G)
echo ==   VS-VFG   : vapoursynth + MEMC_VFG_NV.vpy   (vvfg / NVIDIA VFG)
echo ==   NATIVE   : vf_playkit, D3D11 hwdec straight into D3D12 (DLSS-G)
echo == Every lane runs the same clip, the same multi and the same width;
echo == the numbers compare how many source frames per second each lane takes.
echo == Results go to installer\mpv-FilterBench-result.tsv and the machine
echo == summary plus the result table go to installer\report.txt
echo ==========================================================

:: ---------------- 1. test clip ----------------
:: Optional, to skip the prompts:
::   mpv-FilterBench.bat ["video path"] ["1080p 4k"] [multi]
:: Without a clip, a 10 s 1080p sample is generated once and cached in %TEMP%.
:: The filters only accept hardware frames, so the synthetic source has to be
:: written to a file first and decoded with d3d11va afterwards.
set "CLIP=%~1"
if defined CLIP goto :clip_ready
for %%f in ("%~dp0bench-clip.mkv" "%~dp0bench-clip.mp4" "%~dp0bench-clip.mov") do if exist "%%~f" set "CLIP=%%~f"
if defined CLIP (
    echo == Using the test clip found in the installer directory
    goto :clip_ready
)
echo.
echo == No clip needed: press Enter to generate a 10 s 1080p sample
echo == You can also drop a video into this window or paste a full path
echo == (a real clip is closer to what you actually play)
set /p "CLIP=Video path (Enter = generate): "
if not defined CLIP goto :gen_clip

:clip_ready
set "CLIP=!CLIP:"=!"
if not defined CLIP goto :gen_clip
if not exist "!CLIP!" (
    echo == File not found: !CLIP!
    goto :bye
)
echo == Test clip: !CLIP!
goto :have_clip

:gen_clip
:: mp4 rather than mkv: mkv does not report a frame rate here, the vpy would
:: then call AssumeFPS(0) and fail with "invalid framerate specified"
set "CLIP=!BENCH_LOGDIR!\bench-src.mp4"
if exist "!CLIP!" (
    echo == Reusing the previously generated clip; delete it to regenerate
    goto :have_clip
)
echo == Generating a 10 s 1920x1080 test clip, this happens only once ...
mpv.com --no-config --o="!CLIP!" --of=mp4 --ovc=libx264 --ovcopts=preset=veryfast,crf=23 --frames=300 "av://lavfi:testsrc2=s=1920x1080:r=30" <nul >nul 2>&1
if not exist "!CLIP!" (
    :: fall back to NVENC when the build has no libx264
    mpv.com --no-config --o="!CLIP!" --of=mp4 --ovc=h264_nvenc --frames=300 "av://lavfi:testsrc2=s=1920x1080:r=30" <nul >nul 2>&1
)
if not exist "!CLIP!" (
    echo == Generation failed: no usable h264 encoder in this build, pass a video file instead
    goto :bye
)
set "AUTOCLIP=1"
goto :have_clip

:have_clip
:: ---------------- 2. probe source width ----------------
echo.
echo == Reading source resolution ...
set "PROBE=%TEMP%\mpv-filter-bench-probe.txt"
mpv.com --config=no --vo=null --no-audio --frames=1 --term-playing-msg="BENCHW=${width}" "!CLIP!" <nul >"!PROBE!" 2>&1
set "SRCW="
for /f "tokens=2 delims==" %%a in ('findstr /b "BENCHW=" "!PROBE!"') do set "SRCW=%%a"
del "!PROBE!" >nul 2>&1
if not defined SRCW (
    echo == Could not read the source width; make sure mpv can open this file
    goto :bye
)
echo == Source width !SRCW! px

:: ---------------- 3. pick resolutions ----------------
set "RESSEL=%~2"
if defined RESSEL goto :res_ready
echo.
echo == Which resolutions?
echo ==   1080p = 1920 wide, 2k = 2560 wide, 4k = 3840 wide
echo ==   Several are allowed (spaces or commas); Enter = all of them
set /p "RESSEL=Resolutions (Enter = all 1080p 2k 4k): "

:res_ready
if not defined RESSEL set "RESSEL=1080p 2k 4k"
set "RESSEL=!RESSEL:,= !"

:: ---------------- 4. pick multi ----------------
set "MULTI=%~3"
if defined MULTI goto :multi_ready
echo.
echo == Multi (inserted frames per input pair), 2-6
echo == Note: VS-VFG keeps one CUDA lane per inserted frame (~1.5 GB VRAM each);
echo == 4K with multi above 2 can run out of memory on a 10 GB card and gets skipped
set /p "MULTI=Multi (Enter = 2): "

:multi_ready
if not defined MULTI set "MULTI=2"
echo !MULTI!|findstr /r "^[2-6]$" >nul || set "MULTI=2"
echo == Multi !MULTI!

:: ---------------- 5. precheck all lanes ----------------
:: When a filter fails to initialize mpv just disables it and keeps playing,
:: which yields a falsely high fps. So run 40 frames per lane first and look for
:: the initialization marker in the log; lanes without it are skipped.
:: Drop the old result table up front so a failed run cannot mix in stale rows.
del "!BENCH_OUT!" >nul 2>&1
set "SKIP_VS_DLSSG="
set "SKIP_VS_VFG="
set "SKIP_NAT="
echo.
call :precheck VS-DLSSG
call :precheck VS-VFG
call :precheck NATIVE
if defined SKIP_VS_DLSSG if defined SKIP_VS_VFG if defined SKIP_NAT (
    echo == No lane initialized, nothing to measure. See !BENCH_LOGDIR!\pre-*.log
    goto :report
)

:: ---------------- 6. run every lane per resolution ----------------
> "!BENCH_OUT!" echo tag	WxH	multi	frames	elapsed_s	out_fps	src_fps	note
for %%r in (!RESSEL!) do call :bench_one %%r

echo.
echo ==========================================================
echo == Results (out_fps = presented frames per second, src_fps = out_fps / multi)
echo ==========================================================
type "!BENCH_OUT!"
echo.
echo == Detailed results saved to: !BENCH_OUT!
echo == If a row is missing, its log is in: !BENCH_LOGDIR!
goto :report

:: ================= precheck one lane (40 frames) =================
:precheck
set "PC_TAG=%~1"
set "PC_LOG=!BENCH_LOGDIR!\pre-!PC_TAG!.log"
set "PC_VF="
set "PC_OK="
set "PC_SKIPVAR="
set "VDLSSG_MULTI="
set "VVFG_MULTI="
set "VSSCRIPT_PATH="
if /i "!PC_TAG!"=="VS-DLSSG" (
    set "PC_VF=vapoursynth=!BENCH_VS_DLSSG!"
    set "PC_OK=vapoursynth] initialized."
    set "VDLSSG_MULTI=!MULTI!"
    set "VSSCRIPT_PATH=!BENCH_VSDL!"
    set "PC_SKIPVAR=SKIP_VS_DLSSG"
)
if /i "!PC_TAG!"=="VS-VFG" (
    set "PC_VF=vapoursynth=!BENCH_VS_VFG!"
    set "PC_OK=vapoursynth] initialized."
    set "VVFG_MULTI=!MULTI!"
    set "VSSCRIPT_PATH=!BENCH_VSDL!"
    set "PC_SKIPVAR=SKIP_VS_VFG"
)
if /i "!PC_TAG!"=="NATIVE" (
    set "PC_VF=playkit=multi=!MULTI!:log=no:dll=!BENCH_DLL!:proxy_dir=!BENCH_PROXY!"
    set "PC_OK=vdlssg bridge ready"
    set "PC_SKIPVAR=SKIP_NAT"
)
echo == Precheck !PC_TAG! ...
:: mpv logs to stdout; --log-file keeps a full copy (debug level) to judge by
mpv.com --config=no --include=!BENCH_CONF! --log-file="!PC_LOG!" --frames=40 --vf=!PC_VF! "!CLIP!" <nul >nul 2>nul
set "VDLSSG_MULTI="
set "VVFG_MULTI="
set "VSSCRIPT_PATH="
findstr /i /c:"!PC_OK!" "!PC_LOG!" >nul 2>&1
if errorlevel 1 (
    echo == WARNING: !PC_TAG! did not initialize, skipping this lane. Log: !PC_LOG!
    set "!PC_SKIPVAR!=1"
    findstr /i /c:"cannot load" /c:"could not init" /c:"Script evaluation failed" /c:"Disabling filter" "!PC_LOG!" >nul 2>&1 && echo == Likely a missing file or DLL; the last [e] lines in the log say why
)
exit /b

:: ================= benchmark one resolution =================
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
    echo == Skipping unknown resolution: %~1 - use 1080p / 2k / 4k
    exit /b
)

:: d3d11vpp scales inside the hardware domain; the factor is based on width
set "PSC=%TEMP%\mpv-filter-bench-scale.ps1"
>"!PSC!" echo ([math]::Round(!TW! / !SRCW!, 4)).ToString([Globalization.CultureInfo]::InvariantCulture)
set "SCALE="
for /f "delims=" %%s in ('powershell -NoProfile -ExecutionPolicy Bypass -File "!PSC!"') do set "SCALE=%%s"
del "!PSC!" >nul 2>&1
if not defined SCALE set "SCALE=1"

echo.
echo == ----------------------------------------------------------
echo == Target width !TW! px, scale factor !SCALE!, multi !MULTI!
echo == ----------------------------------------------------------

set "MPV_BENCH_OUT=!BENCH_OUT!"
set "MPV_BENCH_MULTI=!MULTI!"

if not defined SKIP_VS_DLSSG (
    echo == VS-DLSSG ...
    set "MPV_BENCH_TAG=VS-DLSSG-%~1"
    set "VDLSSG_MULTI=!MULTI!"
    set "VSSCRIPT_PATH=!BENCH_VSDL!"
    mpv.com --config=no --include=!BENCH_CONF! --log-file="!BENCH_LOGDIR!\VS-DLSSG-%~1.log" --vf=d3d11vpp=scale=!SCALE!,vapoursynth=!BENCH_VS_DLSSG! --script=!BENCH_LUA! "!CLIP!" <nul 2>nul
    set "VDLSSG_MULTI="
    set "VSSCRIPT_PATH="
)

if not defined SKIP_VS_VFG (
    echo == VS-VFG ...
    set "MPV_BENCH_TAG=VS-VFG-%~1"
    set "VVFG_MULTI=!MULTI!"
    set "VSSCRIPT_PATH=!BENCH_VSDL!"
    mpv.com --config=no --include=!BENCH_CONF! --log-file="!BENCH_LOGDIR!\VS-VFG-%~1.log" --vf=d3d11vpp=scale=!SCALE!,vapoursynth=!BENCH_VS_VFG! --script=!BENCH_LUA! "!CLIP!" <nul 2>nul
    set "VVFG_MULTI="
    set "VSSCRIPT_PATH="
)

if not defined SKIP_NAT (
    echo == NATIVE ...
    set "MPV_BENCH_TAG=NATIVE-%~1"
    set "VSSCRIPT_PATH="
    mpv.com --config=no --include=!BENCH_CONF! --log-file="!BENCH_LOGDIR!\NATIVE-%~1.log" --vf=d3d11vpp=scale=!SCALE!,playkit=multi=!MULTI!:log=no:dll=!BENCH_DLL!:proxy_dir=!BENCH_PROXY! --script=!BENCH_LUA! "!CLIP!" <nul 2>nul
)

set "MPV_BENCH_TAG="
set "MPV_BENCH_OUT="
set "MPV_BENCH_MULTI="
exit /b

:: ================= build the report =================
:report
echo.
echo == Collecting system information (OS / GPU / driver / mpv version) ...
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
    echo == Report written: installer\report.txt - OS, GPU, driver and the result table
) else (
    echo == Report generation failed: PowerShell unavailable, record the machine details manually
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
