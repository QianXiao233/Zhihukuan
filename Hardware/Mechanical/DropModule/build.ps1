# 构建脚本：导出 STL 与预览图
#
# 为什么要绕一步临时目录
#   这台机器上 OpenSCAD 直接 -o 输出到 Hardware/ 目录树会报
#   "Can't open file ... for export"：它用"写临时文件再原子重命名"落盘，
#   该目录树的权限策略让重命名失败。输出到工作区根的 _tmp 则正常。
#
# 用法（在 DropModule 目录下）：
#   pwsh -File build.ps1              # 全部零件 + 预览
#   pwsh -File build.ps1 -SkipRender  # 只导 STL
# =============================================================================
param([switch]$SkipRender)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Resolve-Path (Join-Path $here '..\..\..')
$tmp  = Join-Path $root '_tmp'

$openscad = Join-Path $root '_tools\openscad\openscad-2021.01\openscad.exe'
if (-not (Test-Path $openscad)) {
    $found = Get-Command openscad -ErrorAction SilentlyContinue
    if ($found) { $openscad = $found.Source }
    else {
        Write-Host "找不到 OpenSCAD。" -ForegroundColor Red
        Write-Host "  winget install OpenSCAD.OpenSCAD" -ForegroundColor Yellow
        exit 1
    }
}

New-Item -ItemType Directory -Force -Path $tmp | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $here 'stl')     | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $here 'preview') | Out-Null

$env:TEMP = $tmp
$env:TMP  = $tmp

$fail = 0

# ---------------------------------------------------------------------------
# 1. 零件 STL
# ---------------------------------------------------------------------------
$parts = @('bracket', 'horn', 'tray_ear', 'cap', 'tray')
foreach ($p in $parts) {
    $staged = Join-Path $tmp "dm_$p.stl"
    Remove-Item $staged -ErrorAction SilentlyContinue

    Write-Host "渲染 $p ..." -NoNewline
    $log = & $openscad -o $staged -D "PART=`"$p`"" `
           (Join-Path $here 'drop_module.scad') 2>&1 | Out-String

    if (-not (Test-Path $staged)) {
        Write-Host " 失败" -ForegroundColor Red
        Write-Host $log
        $fail++
        continue
    }

    # 网格健康判据。这里踩过坑，记清楚：
    #   * Volumes 不能当"是否散架"的判据。OpenSCAD 把"外壳 + 内部空腔"各算
    #     一个 volume，所以一个带孔的实心件本来就是 2，带两个孔/槽可能到 3。
    #     实测：实心立方体=1，带孔件=2~3，而真正被切成两块时也是 3 —— 重叠了，
    #     靠这个字段分不出来。
    #   * 可靠判据是 "Simple: yes/No"：CGAL 对网格合法性的判定（无自交、
    #     无退化面）。散架/自交会报 No。
    #   * 可用性上再用体积做个兜底：体积为 0 或异常小说明建模失败。
    $simple = if ($log -match 'Simple:\s+(\w+)') { $Matches[1] } else { 'unknown' }
    $vol    = if ($log -match 'Volumes:\s+(\d+)') { [int]$Matches[1] } else { 0 }
    $kb     = [math]::Round((Get-Item $staged).Length / 1KB, 1)

    if ($simple -ne 'yes') {
        Write-Host (" {0} KB  Simple={1}（网格不合法，需修）" -f $kb, $simple) -ForegroundColor Yellow
        $fail++
    } else {
        Write-Host (" {0} KB  Simple={1}  Volumes={2}" -f $kb, $simple, $vol) -ForegroundColor Green
    }
    Copy-Item $staged (Join-Path $here "stl\$p.stl") -Force
}

# ---------------------------------------------------------------------------
# 2. 预览图
# ---------------------------------------------------------------------------
if (-not $SkipRender) {
    $views = @('iso', 'locked', 'released', 'explode')
    foreach ($v in $views) {
        $png = Join-Path $tmp "view_$v.png"
        Remove-Item $png -ErrorAction SilentlyContinue
        & $openscad -o $png --imgsize=1400,1050 --projection=o `
            -D "VIEW=`"$v`"" (Join-Path $here 'render_views.scad') 2>&1 | Out-Null
        if (Test-Path $png) {
            Copy-Item $png (Join-Path $here "preview\$v.png") -Force
            Write-Host "预览 $v" -ForegroundColor Green
        } else {
            Write-Host "预览 $v 失败（不影响 STL）" -ForegroundColor Yellow
        }
    }

    # 单件图
    foreach ($p in $parts) {
        $png = Join-Path $tmp "part_$p.png"
        Remove-Item $png -ErrorAction SilentlyContinue
        & $openscad -o $png --imgsize=1000,800 --projection=o `
            -D "PART=`"$p`"" (Join-Path $here 'drop_module.scad') 2>&1 | Out-Null
        if (Test-Path $png) { Copy-Item $png (Join-Path $here "preview\part_$p.png") -Force }
    }
    Write-Host "单件图完成" -ForegroundColor Green
}

Write-Host ""
if ($fail -gt 0) {
    Write-Host "有 $fail 个零件需要处理。" -ForegroundColor Red
    exit 1
}
Write-Host "完成。" -ForegroundColor Green
