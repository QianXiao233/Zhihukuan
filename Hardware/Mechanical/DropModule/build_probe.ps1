# 验证件构建脚本
#
# 输出到 _tmp 再拷回来 —— 原因同 build.ps1：
# OpenSCAD 直接写 Hardware/ 目录树会报 "Can't open file ... for export"。
#
# 用法：pwsh -File build_probe.ps1

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Resolve-Path (Join-Path $here '..\..\..')
$tmp  = Join-Path $root '_tmp'

$openscad = Join-Path $root '_tools\openscad\openscad-2021.01\openscad.exe'
if (-not (Test-Path $openscad)) {
    $found = Get-Command openscad -ErrorAction SilentlyContinue
    if ($found) { $openscad = $found.Source }
    else { Write-Host "找不到 OpenSCAD" -ForegroundColor Red; exit 1 }
}

New-Item -ItemType Directory -Force -Path $tmp | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $here 'stl')     | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $here 'preview') | Out-Null
$env:TEMP = $tmp
$env:TMP  = $tmp

$fail = 0
foreach ($p in @('boom', 'loop', 'pin')) {
    $staged = Join-Path $tmp "probe_$p.stl"
    Remove-Item $staged -ErrorAction SilentlyContinue
    Write-Host "导出 $p ..." -NoNewline
    $log = & $openscad -o $staged -D "PART=`"$p`"" `
           (Join-Path $here 'hang_probe.scad') 2>&1 | Out-String

    if (-not (Test-Path $staged)) {
        Write-Host " 失败" -ForegroundColor Red
        Write-Host $log
        $fail++
        continue
    }
    $facets = if ($log -match 'Facets:\s+(\d+)') { [int]$Matches[1] } else { 0 }
    $kb = [math]::Round((Get-Item $staged).Length / 1KB, 1)
    if ($facets -lt 50) {
        Write-Host (" {0} KB  Facets={1}  <- 面数异常" -f $kb, $facets) -ForegroundColor Yellow
        $fail++
    } else {
        Write-Host (" {0} KB  Facets={1}" -f $kb, $facets) -ForegroundColor Green
    }
    Copy-Item $staged (Join-Path $here "stl\probe_$p.stl") -Force
}

# 装配预览
$scad = Join-Path $tmp '_probe_view.scad'
@'
_HP_INCLUDED = true;
include <hang_probe.scad>
rotate([20, 0, -35]) assembly();
'@ | Set-Content $scad -Encoding UTF8

$png = Join-Path $tmp 'probe_view.png'
Remove-Item $png -ErrorAction SilentlyContinue
& $openscad -o $png --imgsize=1200,900 --projection=o $scad 2>&1 | Out-Null
if (Test-Path $png) {
    Copy-Item $png (Join-Path $here 'preview\probe_assembly.png') -Force
    Write-Host "预览已生成" -ForegroundColor Green
}

Write-Host ""
if ($fail -gt 0) { Write-Host "有 $fail 个零件失败" -ForegroundColor Red; exit 1 }
Write-Host "完成。" -ForegroundColor Green
