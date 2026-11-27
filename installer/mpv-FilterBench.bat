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
set "BENCH_TMP=%TEMP%\mpv-filter-bench\result.tmp"
set "BENCH_LOGDIR=%TEMP%\mpv-filter-bench"
if not exist "!BENCH_LOGDIR!" mkdir "!BENCH_LOGDIR!" >nul 2>&1
:: --vf does not expand ~~/, so all paths are relative to the package root
set "BENCH_VS_DLSSG=portable_config/vs/MEMC_DLSSG_NV.vpy"
set "BENCH_VS_VFG=portable_config/vs/MEMC_VFG_NV.vpy"
set "BENCH_DLL=vs-plugins/vdlssg.dll"
set "BENCH_PROXY=vs-plugins/dlss45"
:: Initialization markers: mpv disables a filter that fails and keeps playing, so
:: every run is judged by these lines in its log instead of trusting the fps
set "BENCH_OK_VS=vapoursynth] initialized."
set "BENCH_OK_NAT=vdlssg bridge ready"
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
echo == Every lane runs the same clip at every resolution and multi;
echo == the numbers say how many source frames per second each lane takes, and
echo == + / - marks whether that is enough to keep up with the clip.
echo == Each run warms up first: the clock starts only after the frame rate has
echo == settled, so model init / CUDA warm-up is not counted in the numbers.
echo == A run still going after 40 s is written off as run-timeout (usually a
echo == lane that spilled out of VRAM), so one bad cell cannot stall the sweep.
echo == Results go to installer\mpv-FilterBench-result.tsv and the machine
echo == summary plus the result table go to installer\report.txt
echo ==========================================================

:: ---------------- 1. test clip ----------------
:: Optional, to skip the prompts:
::   mpv-FilterBench.bat ["video path"] ["1080p 4k"] [multi]
:: Without a clip, a 30 s 1080p sample is generated once and cached in %TEMP%.
:: 30 s so every lane still has a tail to measure after the warm-up: at a high
:: frame rate a 10 s clip is spent before the rate even settles.
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
echo == No clip needed: press Enter to generate a 30 s 1080p sample
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
set "CLIP=!BENCH_LOGDIR!\bench-src-30s.mp4"
if exist "!CLIP!" (
    echo == Reusing the previously generated clip; delete it to regenerate
    goto :have_clip
)
echo == Generating a 30 s 1920x1080 test clip, this happens only once ...
mpv.com --no-config --o="!CLIP!" --of=mp4 --ovc=libx264 --ovcopts=preset=veryfast,crf=23 --frames=900 "av://lavfi:testsrc2=s=1920x1080:r=30" <nul >nul 2>&1
if not exist "!CLIP!" (
    :: fall back to NVENC when the build has no libx264
    mpv.com --no-config --o="!CLIP!" --of=mp4 --ovc=h264_nvenc --frames=900 "av://lavfi:testsrc2=s=1920x1080:r=30" <nul >nul 2>&1
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
mpv.com --config=no --vo=null --no-audio --frames=1 --term-playing-msg="BENCHW=${width}x${height}" "!CLIP!" <nul >"!PROBE!" 2>&1
set "SRCW="
set "SRCH="
for /f "tokens=2 delims==" %%a in ('findstr /b "BENCHW=" "!PROBE!"') do for /f "tokens=1,2 delims=x" %%i in ("%%a") do set "SRCW=%%i" & set "SRCH=%%j"
del "!PROBE!" >nul 2>&1
if not defined SRCW (
    echo == Could not read the source resolution; make sure mpv can open this file
    goto :bye
)
echo == Source resolution !SRCW!x!SRCH!

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
:: Several multi values are allowed: the point of the sweep is to show which
:: resolution x multi combinations this machine can keep up with.
set "MULTISEL=%~3"
if defined MULTISEL goto :multi_ready
echo.
echo == Multi (inserted frames per input pair), 2-6
echo ==   Several are allowed; Enter = the whole 2-6 sweep
echo ==   Note: VS-VFG keeps one CUDA lane per inserted frame, about 1.5 GB VRAM
echo ==   each; 4K at a high multi can run out of memory on a 10 GB card. Such
echo ==   combinations show up as - rows instead of stopping the sweep
set /p "MULTISEL=Multi (Enter = 2 3 4 5 6): "

:multi_ready
if not defined MULTISEL set "MULTISEL=2 3 4 5 6"
set "MULTISEL=!MULTISEL:,= !"
:: keep only 2-6; the first one left is used for precheck
set "VALID="
for %%m in (!MULTISEL!) do (
    set "TOK=%%m"
    if "!TOK!"=="2" set "VALID=!VALID! 2"
    if "!TOK!"=="3" set "VALID=!VALID! 3"
    if "!TOK!"=="4" set "VALID=!VALID! 4"
    if "!TOK!"=="5" set "VALID=!VALID! 5"
    if "!TOK!"=="6" set "VALID=!VALID! 6"
)
if not defined VALID set "VALID= 2"
set "MULTISEL=!VALID:~1!"
set "PMULTI="
for %%m in (!MULTISEL!) do if not defined PMULTI set "PMULTI=%%m"
echo == Multi !MULTISEL!

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

:: ---------------- 6. run every lane per resolution x multi ----------------
> "!BENCH_OUT!" echo tag	WxH	multi	frames	elapsed_s	out_fps	src_fps	note
for %%r in (!RESSEL!) do for %%m in (!MULTISEL!) do call :bench_one %%r %%m

echo.
echo ==========================================================
echo == Results (out_fps = presented frames per second, src_fps = out_fps / multi)
echo == + means src_fps covers the clip frame rate, - means it does not
echo == warm= in the note is how many seconds of warm-up were skipped before
echo == the clock started; a row full of dashes means that lane could not run
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
    set "PC_OK=!BENCH_OK_VS!"
    set "VDLSSG_MULTI=!PMULTI!"
    set "VSSCRIPT_PATH=!BENCH_VSDL!"
    set "PC_SKIPVAR=SKIP_VS_DLSSG"
)
if /i "!PC_TAG!"=="VS-VFG" (
    set "PC_VF=vapoursynth=!BENCH_VS_VFG!"
    set "PC_OK=!BENCH_OK_VS!"
    set "VVFG_MULTI=!PMULTI!"
    set "VSSCRIPT_PATH=!BENCH_VSDL!"
    set "PC_SKIPVAR=SKIP_VS_VFG"
)
if /i "!PC_TAG!"=="NATIVE" (
    set "PC_VF=playkit=multi=!PMULTI!:log=no:dll=!BENCH_DLL!:proxy_dir=!BENCH_PROXY!"
    set "PC_OK=!BENCH_OK_NAT!"
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

:: ================= benchmark one resolution x multi =================
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
set "MULTI=%~2"

:: d3d11vpp scales inside the hardware domain; the factor is based on width and
:: the target height follows the source aspect ratio, rounded to even
set "PSC=%TEMP%\mpv-filter-bench-scale.ps1"
>"!PSC!" echo $inv = [Globalization.CultureInfo]::InvariantCulture
>>"!PSC!" echo ([math]::Round(!TW! / !SRCW!, 4)).ToString($inv)
>>"!PSC!" echo ([math]::Round(!TW! * !SRCH! / !SRCW! / 2, 0) * 2).ToString($inv)
set "SCALE="
set "TGH="
set "PSCN=0"
for /f "delims=" %%s in ('powershell -NoProfile -ExecutionPolicy Bypass -File "!PSC!"') do (
    if "!PSCN!"=="0" set "SCALE=%%s"
    if "!PSCN!"=="1" set "TGH=%%s"
    set /a PSCN+=1
)
del "!PSC!" >nul 2>&1
if not defined SCALE set "SCALE=1"
if not defined TGH set "TGH=0"
set "WXH=!TW!x!TGH!"

echo.
echo == ----------------------------------------------------------
echo == Target !WXH!, scale factor !SCALE!, multi !MULTI!
echo == ----------------------------------------------------------

set "MPV_BENCH_OUT=!BENCH_OUT!"
set "MPV_BENCH_MULTI=!MULTI!"

set "LANE_NOTE=failed"
if defined SKIP_VS_DLSSG set "LANE_NOTE=lane-skipped"
if not defined SKIP_VS_DLSSG (
    echo == VS-DLSSG %~1 !MULTI!x ...
    set "MPV_BENCH_TAG=VS-DLSSG-%~1-!MULTI!x"
    set "VDLSSG_MULTI=!MULTI!"
    set "VSSCRIPT_PATH=!BENCH_VSDL!"
    mpv.com --config=no --include=!BENCH_CONF! --log-file="!BENCH_LOGDIR!\VS-DLSSG-%~1-!MULTI!x.log" --vf=d3d11vpp=scale=!SCALE!,vapoursynth=!BENCH_VS_DLSSG! --script=!BENCH_LUA! "!CLIP!" <nul 2>nul
    set "VDLSSG_MULTI="
    set "VSSCRIPT_PATH="
    call :check_run "VS-DLSSG-%~1-!MULTI!x" "!BENCH_LOGDIR!\VS-DLSSG-%~1-!MULTI!x.log" "!BENCH_OK_VS!"
)
call :need_row "VS-DLSSG-%~1-!MULTI!x" "!WXH!" "!MULTI!" "!LANE_NOTE!"

set "LANE_NOTE=failed"
if defined SKIP_VS_VFG set "LANE_NOTE=lane-skipped"
if not defined SKIP_VS_VFG (
    echo == VS-VFG %~1 !MULTI!x ...
    set "MPV_BENCH_TAG=VS-VFG-%~1-!MULTI!x"
    set "VVFG_MULTI=!MULTI!"
    set "VSSCRIPT_PATH=!BENCH_VSDL!"
    mpv.com --config=no --include=!BENCH_CONF! --log-file="!BENCH_LOGDIR!\VS-VFG-%~1-!MULTI!x.log" --vf=d3d11vpp=scale=!SCALE!,vapoursynth=!BENCH_VS_VFG! --script=!BENCH_LUA! "!CLIP!" <nul 2>nul
    set "VVFG_MULTI="
    set "VSSCRIPT_PATH="
    call :check_run "VS-VFG-%~1-!MULTI!x" "!BENCH_LOGDIR!\VS-VFG-%~1-!MULTI!x.log" "!BENCH_OK_VS!"
)
call :need_row "VS-VFG-%~1-!MULTI!x" "!WXH!" "!MULTI!" "!LANE_NOTE!"

set "LANE_NOTE=failed"
if defined SKIP_NAT set "LANE_NOTE=lane-skipped"
if not defined SKIP_NAT (
    echo == NATIVE %~1 !MULTI!x ...
    set "MPV_BENCH_TAG=NATIVE-%~1-!MULTI!x"
    set "VSSCRIPT_PATH="
    mpv.com --config=no --include=!BENCH_CONF! --log-file="!BENCH_LOGDIR!\NATIVE-%~1-!MULTI!x.log" --vf=d3d11vpp=scale=!SCALE!,playkit=multi=!MULTI!:log=no:dll=!BENCH_DLL!:proxy_dir=!BENCH_PROXY! --script=!BENCH_LUA! "!CLIP!" <nul 2>nul
    call :check_run "NATIVE-%~1-!MULTI!x" "!BENCH_LOGDIR!\NATIVE-%~1-!MULTI!x.log" "!BENCH_OK_NAT!"
)
call :need_row "NATIVE-%~1-!MULTI!x" "!WXH!" "!MULTI!" "!LANE_NOTE!"

set "MPV_BENCH_TAG="
set "MPV_BENCH_OUT="
set "MPV_BENCH_MULTI="
exit /b

:: ================= drop the row of a run where the filter never came up =====
:: A filter that fails at a given multi is just disabled by mpv, which then
:: plays at full speed; the probe would record that fake number. Judge the run
:: by the initialization marker in its own log and remove its row if missing.
:check_run
findstr /i /c:"%~3" "%~2" >nul 2>&1
if not errorlevel 1 exit /b
findstr /v /b /c:"%~1" "!BENCH_OUT!" >"!BENCH_TMP!" 2>nul
move /y "!BENCH_TMP!" "!BENCH_OUT!" >nul 2>&1
exit /b

:: ================= append a placeholder row for a run without data =================
:: mpv stays silent when a filter cannot initialize for this multi, so without
:: this the table would just have a gap instead of an explicit "not supported"
:need_row
findstr /b /c:"%~1" "!BENCH_OUT!" >nul 2>&1
if not errorlevel 1 exit /b
>>"!BENCH_OUT!" echo %~1	%~2	%~3	-	-	-	-	%~4
exit /b

:: ================= build the report =================
:report
echo.
echo == Collecting system information (OS / GPU / driver / mpv version) ...
set "MPV_BENCH_REPORT=installer\report.txt"
set "MPV_BENCH_TSV=!BENCH_OUT!"
set "MPV_BENCH_CLIP=!CLIP!"
set "MPV_BENCH_SRCWH=!SRCW!x!SRCH!"
set "MPV_BENCH_RES=!RESSEL!"
set "MPV_BENCH_MULTI=!MULTISEL!"
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
set "MPV_BENCH_SRCWH="
set "MPV_BENCH_RES="
set "MPV_BENCH_MULTI="
set "MPV_BENCH_AUTOCLIP="
goto :bye

:bye
echo.
pause
endlocal
