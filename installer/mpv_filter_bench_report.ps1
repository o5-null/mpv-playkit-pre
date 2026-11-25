# 生成跑分报告：系统 / 显卡 / 驱动 / 播放器 + 测试条件 + 结果表
# 由 mpv-补帧滤镜跑分.bat 调用，参数全部通过 MPV_BENCH_* 环境变量传入。
$ErrorActionPreference = 'SilentlyContinue'

function Env([string]$n) { [Environment]::GetEnvironmentVariable($n) }

$reportPath = Env 'MPV_BENCH_REPORT'
if ([string]::IsNullOrEmpty($reportPath)) { $reportPath = 'installer\report.txt' }
$tsvPath = Env 'MPV_BENCH_TSV'

$lines = New-Object System.Collections.Generic.List[string]

# ---------- 基本信息 ----------
$lines.Add('mpv 补帧滤镜跑分报告')
$lines.Add('生成时间：' + (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))
$lines.Add('')

# ---------- 系统 ----------
$lines.Add('==== 系统 ====')
$os = Get-CimInstance Win32_OperatingSystem
if ($os) {
    $lines.Add('操作系统    : ' + $os.Caption)
    $lines.Add('版本        : ' + $os.Version + ' (build ' + $os.BuildNumber + ', ' + $os.OSArchitecture + ')')
    if ($os.TotalVisibleMemorySize) {
        $lines.Add(('物理内存    : {0:N1} GB' -f ($os.TotalVisibleMemorySize / 1MB)))
    }
}
foreach ($c in @(Get-CimInstance Win32_Processor)) {
    $lines.Add('处理器      : ' + $c.Name.Trim() + ' / ' + $c.NumberOfCores + '核' +
        $c.NumberOfLogicalProcessors + '线程 / ' + $c.MaxClockSpeed + ' MHz')
}

# ---------- 显卡 / 驱动 ----------
$lines.Add('')
$lines.Add('==== 显卡 / 驱动 ====')
foreach ($g in @(Get-CimInstance Win32_VideoController)) {
    $lines.Add('显卡        : ' + $g.Name)
    $lines.Add('  驱动版本  : ' + $g.DriverVersion + '  (' + $g.DriverDate + ')')
    if ($g.AdapterRAM -gt 0) {
        $lines.Add(('  显存      : {0:N1} GB（4GB 以上的卡这里常报错，以下面 nvidia-smi 为准）' -f ([double]$g.AdapterRAM / 1GB)))
    }
    if ($g.CurrentHorizontalResolution) {
        $lines.Add('  当前显示  : ' + $g.CurrentHorizontalResolution + 'x' + $g.CurrentVerticalResolution +
            ' @ ' + $g.CurrentRefreshRate + ' Hz')
    }
}

# nvidia-smi 的显存/驱动版本最准
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
$smiPath = if ($smi) { $smi.Source } else { $null }
if (-not $smiPath) {
    foreach ($p in @("$env:SystemRoot\System32\nvidia-smi.exe", 'C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe')) {
        if (Test-Path -LiteralPath $p) { $smiPath = $p; break }
    }
}
if ($smiPath) {
    foreach ($l in @(& $smiPath --query-gpu=name,driver_version,memory.total --format=csv,noheader)) {
        if ($l) { $lines.Add('nvidia-smi  : ' + $l.Trim()) }
    }
}

# ---------- 播放器 ----------
$lines.Add('')
$lines.Add('==== 播放器 ====')
$mpv = Env 'MPV_BENCH_MPV'
if ([string]::IsNullOrEmpty($mpv)) { $mpv = 'mpv.com' }
# PowerShell 不会在命令行名里查当前目录，相对文件名要自己补成绝对路径
if (-not (Test-Path -LiteralPath $mpv)) {
    $cand = Join-Path (Get-Location).Path $mpv
    if (Test-Path -LiteralPath $cand) { $mpv = $cand }
}
$ver = @(& $mpv --version 2>$null | Select-Object -First 4)
if ($ver.Count -gt 0) { $lines.Add('mpv         : ' + $ver[0].Trim()) }
foreach ($l in $ver) {
    if ($l -match 'FFmpeg version') { $lines.Add('FFmpeg      : ' + $l.Trim()); break }
}

# ---------- 测试条件 ----------
$lines.Add('')
$lines.Add('==== 测试条件 ====')
$clip = Env 'MPV_BENCH_CLIP'
if (Env 'MPV_BENCH_AUTOCLIP') { $clip = $clip + '（脚本自动生成）' }
$lines.Add('素材        : ' + $clip)
$lines.Add('源宽度      : ' + (Env 'MPV_BENCH_SRCW') + ' px')
$lines.Add('目标分辨率  : ' + (Env 'MPV_BENCH_RES'))
$lines.Add('补帧倍数    : multi=' + (Env 'MPV_BENCH_MULTI'))
$lines.Add('播放参数    : --untimed --frames=600 --d3d11-flip=no --d3d11-sync-interval=0 --autofit=960x540')
$lines.Add('VS 滤镜     : --vf=d3d11vpp=scale=W/SRCW,vapoursynth=portable_config/vs/MEMC_DLSSG_NV.vpy')
$lines.Add('原生滤镜    : --vf=d3d11vpp=scale=W/SRCW,playkit=multi=N:log=no:dll=vs-plugins/vdlssg.dll:proxy_dir=vs-plugins/dlss45')

# ---------- 结果 ----------
$lines.Add('')
$lines.Add('==== 结果 ====（out_fps = 补帧后每秒呈现帧数，src_fps = 除以倍数后的等效源帧数）')
$rows = @()
if ($tsvPath -and (Test-Path -LiteralPath $tsvPath)) {
    $rows = @(Get-Content -LiteralPath $tsvPath | Where-Object { $_.Trim() -ne '' })
} 
if ($rows.Count -le 1) {
    $lines.Add('（本次没有产生结果：滤镜初始化失败或全部跳过）')
} else {
    # 按列对齐输出，方便直接贴给别人看
    $table = @()
    foreach ($r in $rows) { $table += ,($r -split "`t") }
    $widths = @()
    for ($i = 0; $i -lt 8; $i++) {
        $w = 0
        foreach ($r in $table) { if ($i -lt $r.Count -and $r[$i].Length -gt $w) { $w = $r[$i].Length } }
        $widths += $w
    }
    foreach ($r in $table) {
        $cells = @()
        for ($i = 0; $i -lt 8; $i++) {
            $v = if ($i -lt $r.Count) { $r[$i] } else { '' }
            $cells += $v.PadRight($widths[$i])
        }
        $lines.Add((($cells -join '  ').TrimEnd()))
    }
}

# ---------- 写文件 ----------
$text = ($lines -join "`r`n") + "`r`n"
$dir = Split-Path -Parent $reportPath
if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
if ([IO.Path]::IsPathRooted($reportPath)) { $full = $reportPath } else { $full = Join-Path (Get-Location).Path $reportPath }
[IO.File]::WriteAllText($full, $text, (New-Object Text.UTF8Encoding($true)))
'报告已写入 ' + $full
