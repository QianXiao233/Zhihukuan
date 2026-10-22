#requires -Version 5.1
<#
智护库安 · 本地视频工具
- 管理 MediaMTX 和多个 FFmpeg 推流进程
- 支持本机摄像头（dshow）和 IP 摄像头（RTSP）
- 不做开机自启，只做手动启停

用法：
  .\zhka-video.ps1                 进入菜单
  .\zhka-video.ps1 status          查看状态
  .\zhka-video.ps1 start           启动全部
  .\zhka-video.ps1 start -Name cam1
  .\zhka-video.ps1 stop            停止全部
  .\zhka-video.ps1 stop -Name cam1
  .\zhka-video.ps1 add             交互式新增摄像头
  .\zhka-video.ps1 add -Name cam2 -Type dshow -Source "USB Camera"
  .\zhka-video.ps1 remove -Name cam2
  .\zhka-video.ps1 devices         列出本机摄像头
  .\zhka-video.ps1 url             显示播放地址
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Command = 'menu',
    [string]$Name,
    [string]$Type,
    [string]$Source,
    [string]$Label,
    [int]$Width = 1280,
    [int]$Height = 720,
    [int]$Fps = 30,
    [string]$Bitrate = '1500k',
    [switch]$Copy,
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'

$Root = Join-Path $env:LOCALAPPDATA 'ZhkaVideo'
$ConfigPath = Join-Path $Root 'config.json'
$LogDir = Join-Path $Root 'logs'
$RunDir = Join-Path $Root 'run'
$script:Cfg = $null

function Info($text) { Write-Host $text -ForegroundColor Cyan }
function Ok($text) { Write-Host $text -ForegroundColor Green }
function Warn($text) { Write-Host $text -ForegroundColor Yellow }
function Fail($text) { Write-Host $text -ForegroundColor Red }

function Find-Exe([string]$name, [string]$pattern) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $found = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages') `
        -Recurse -Filter $pattern -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { return $found.FullName }
    return $null
}

function Get-VideoDevices([string]$ffmpeg) {
    if (-not $ffmpeg -or -not (Test-Path $ffmpeg)) { return @() }
    $output = & $ffmpeg -hide_banner -list_devices true -f dshow -i dummy 2>&1
    $devices = @()
    foreach ($line in $output) {
        $match = [regex]::Match([string]$line, '"([^"]+)"\s+\(video\)')
        if ($match.Success) { $devices += $match.Groups[1].Value }
    }
    return $devices
}

function Save-Config {
    $script:Cfg | ConvertTo-Json -Depth 10 | Set-Content -Path $ConfigPath -Encoding UTF8
}

function New-DefaultConfig {
    $ffmpeg = Find-Exe 'ffmpeg.exe' 'ffmpeg.exe'
    $mediamtx = Find-Exe 'mediamtx.exe' 'mediamtx.exe'
    $devices = Get-VideoDevices $ffmpeg
    $cameras = @()
    if ($devices.Count -gt 0) {
        $cameras = @([ordered]@{
            name = 'cam1'
            label = '本机摄像头'
            type = 'dshow'
            source = $devices[0]
            width = 1280
            height = 720
            fps = 30
            bitrate = '1500k'
            copy = $false
            enabled = $true
        })
    }
    $workDir = ''
    if ($mediamtx) { $workDir = Split-Path $mediamtx }
    return [ordered]@{
        ffmpeg = $ffmpeg
        mediaMtx = [ordered]@{
            exe = $mediamtx
            workDir = $workDir
            rtmpPort = 1935
            webrtcPort = 8889
            hlsPort = 8888
        }
        cameras = $cameras
    }
}

function Load-Config {
    foreach ($dir in @($Root, $LogDir, $RunDir)) {
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    }
    if (-not (Test-Path $ConfigPath)) {
        $script:Cfg = New-DefaultConfig
        Save-Config
        return
    }
    $raw = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $script:Cfg = $raw
    $changed = $false
    if (-not $script:Cfg.ffmpeg -or -not (Test-Path $script:Cfg.ffmpeg)) {
        $script:Cfg.ffmpeg = Find-Exe 'ffmpeg.exe' 'ffmpeg.exe'
        $changed = $true
    }
    if (-not $script:Cfg.mediaMtx.exe -or -not (Test-Path $script:Cfg.mediaMtx.exe)) {
        $script:Cfg.mediaMtx.exe = Find-Exe 'mediamtx.exe' 'mediamtx.exe'
        if ($script:Cfg.mediaMtx.exe) { $script:Cfg.mediaMtx.workDir = Split-Path $script:Cfg.mediaMtx.exe }
        $changed = $true
    }
    if ($changed) { Save-Config }
}

function Get-Cameras {
    if ($null -eq $script:Cfg.cameras) { return @() }
    return @($script:Cfg.cameras | Where-Object { $_ -and $_.name })
}
function Get-Camera([string]$cameraName) {
    return (Get-Cameras | Where-Object { $_.name -eq $cameraName } | Select-Object -First 1)
}

function Get-PortOwner([int]$port) {
    try {
        return (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction Stop |
            Select-Object -First 1 -ExpandProperty OwningProcess)
    } catch {
        return $null
    }
}

function Test-Port([int]$port) { return [bool](Get-PortOwner $port) }

function Get-CameraProcess([string]$cameraName) {
    $pidFile = Join-Path $RunDir "$cameraName.pid"
    if (Test-Path $pidFile) {
        $savedPid = (Get-Content $pidFile -Raw).Trim()
        $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -eq 'ffmpeg') {
            $wmi = Get-CimInstance Win32_Process -Filter "ProcessId=$savedPid" -ErrorAction SilentlyContinue
            $pattern = "127\.0\.0\.1:$($script:Cfg.mediaMtx.rtmpPort)/$([regex]::Escape($cameraName))(\s|$)"
            if ($wmi -and $wmi.CommandLine -match $pattern) { return $proc }
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
    $pattern = "127\.0\.0\.1:$($script:Cfg.mediaMtx.rtmpPort)/$([regex]::Escape($cameraName))(\s|$)"
    foreach ($wmi in (Get-CimInstance Win32_Process -Filter "Name='ffmpeg.exe'" -ErrorAction SilentlyContinue)) {
        if ($wmi.CommandLine -match $pattern) {
            return (Get-Process -Id $wmi.ProcessId -ErrorAction SilentlyContinue)
        }
    }
    return $null
}

function Start-MediaMtx {
    $port = [int]$script:Cfg.mediaMtx.rtmpPort
    if (Test-Port $port) {
        Ok "MediaMTX 已在运行（RTMP 端口 $port）"
        return
    }
    $exe = $script:Cfg.mediaMtx.exe
    if (-not $exe -or -not (Test-Path $exe)) {
        throw "找不到 mediamtx.exe，请先执行：winget install bluenviron.mediamtx"
    }
    $workDir = $script:Cfg.mediaMtx.workDir
    if (-not $workDir) { $workDir = Split-Path $exe }
    $out = Join-Path $LogDir 'mediamtx.out.log'
    $err = Join-Path $LogDir 'mediamtx.err.log'
    Start-Process -FilePath $exe -WorkingDirectory $workDir -WindowStyle Hidden `
        -RedirectStandardOutput $out -RedirectStandardError $err | Out-Null
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-Port $port) {
            Ok "MediaMTX 已启动"
            return
        }
    }
    throw "MediaMTX 启动超时，请查看日志：$out / $err"
}

function Stop-MediaMtx {
    $proc = Get-Process mediamtx -ErrorAction SilentlyContinue
    if (-not $proc) {
        Info 'MediaMTX 未运行'
        return
    }
    $proc | Stop-Process -Force
    Ok 'MediaMTX 已停止'
}

function Build-FfmpegArgs($camera) {
    $rtmpPort = $script:Cfg.mediaMtx.rtmpPort
    $url = "rtmp://127.0.0.1:$rtmpPort/$($camera.name)"
    $fps = if ($camera.fps) { [int]$camera.fps } else { 30 }
    $width = if ($camera.width) { [int]$camera.width } else { 1280 }
    $height = if ($camera.height) { [int]$camera.height } else { 720 }
    $bitrate = if ($camera.bitrate) { $camera.bitrate } else { '1500k' }

    if ($camera.type -eq 'dshow') {
        if (-not $camera.source) { throw "摄像头 $($camera.name) 没有配置设备名" }
        return '-hide_banner -loglevel info -f dshow -rtbufsize 100M ' +
            "-framerate $fps -video_size ${width}x${height} -i video=`"$($camera.source)`" " +
            "-c:v libx264 -preset veryfast -tune zerolatency -b:v $bitrate -pix_fmt yuv420p -g $fps " +
            "-f flv $url"
    }

    if ($camera.type -eq 'rtsp') {
        if (-not $camera.source) { throw "摄像头 $($camera.name) 没有配置 RTSP 地址" }
        if ($camera.copy -ne $false) {
            return "-hide_banner -loglevel info -rtsp_transport tcp -i `"$($camera.source)`" -c copy -f flv $url"
        }
        return '-hide_banner -loglevel info -rtsp_transport tcp ' +
            "-i `"$($camera.source)`" " +
            "-c:v libx264 -preset veryfast -tune zerolatency -b:v $bitrate -pix_fmt yuv420p -g $fps " +
            "-f flv $url"
    }

    throw "摄像头 $($camera.name) 的类型未知：$($camera.type)"
}

function Start-Camera($camera) {
    if (-not $camera) { throw '摄像头不存在' }
    if ($camera.enabled -eq $false) {
        Warn "摄像头 $($camera.name) 已禁用，跳过"
        return
    }
    if (Get-CameraProcess $camera.name) {
        Ok "摄像头 $($camera.name) 已在运行"
        return
    }
    if (-not $script:Cfg.ffmpeg -or -not (Test-Path $script:Cfg.ffmpeg)) {
        throw '找不到 ffmpeg.exe，请先执行：winget install Gyan.FFmpeg'
    }
    Start-MediaMtx
    $log = Join-Path $LogDir "$($camera.name).log"
    $args = Build-FfmpegArgs $camera
    $proc = Start-Process -FilePath $script:Cfg.ffmpeg -ArgumentList $args -WindowStyle Hidden `
        -RedirectStandardError $log -PassThru
    Set-Content -Path (Join-Path $RunDir "$($camera.name).pid") -Value $proc.Id -Encoding ASCII
    Start-Sleep -Milliseconds 2500
    if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) {
        $tail = Get-Content $log -Tail 12 -ErrorAction SilentlyContinue
        throw "摄像头 $($camera.name) 启动失败，日志：`n$($tail -join "`n")"
    }
    Ok "摄像头 $($camera.name) 已启动（PID $($proc.Id)）"
    Info "  WebRTC: http://127.0.0.1:$($script:Cfg.mediaMtx.webrtcPort)/$($camera.name)"
    Info "  HLS   : http://127.0.0.1:$($script:Cfg.mediaMtx.hlsPort)/$($camera.name)/index.m3u8"
}

function Stop-Camera([string]$cameraName) {
    $proc = Get-CameraProcess $cameraName
    if (-not $proc) {
        Remove-Item (Join-Path $RunDir "$cameraName.pid") -Force -ErrorAction SilentlyContinue
        Info "摄像头 $cameraName 未运行"
        return
    }
    Stop-Process -Id $proc.Id -Force
    Remove-Item (Join-Path $RunDir "$cameraName.pid") -Force -ErrorAction SilentlyContinue
    Ok "摄像头 $cameraName 已停止"
}

function Start-All {
    $cameras = Get-Cameras
    if ($cameras.Count -eq 0) {
        Warn '还没有配置摄像头，请先执行 add'
        return
    }
    Start-MediaMtx
    foreach ($camera in $cameras) {
        try { Start-Camera $camera } catch { Fail $_.Exception.Message }
    }
}

function Stop-All {
    foreach ($camera in (Get-Cameras)) {
        Stop-Camera $camera.name
    }
}

function Show-Status {
    $port = [int]$script:Cfg.mediaMtx.rtmpPort
    $owner = Get-PortOwner $port
    if ($owner) {
        $proc = Get-Process -Id $owner -ErrorAction SilentlyContinue
        $name = if ($proc) { $proc.ProcessName } else { '未知进程' }
        Ok "MediaMTX: 运行中（PID $owner / $name，RTMP $port）"
    } else {
        Warn 'MediaMTX: 未运行'
    }
    Write-Host ''
    Write-Host ('{0,-10} {1,-8} {2,-8} {3,-18} {4}' -f '名称', '状态', 'PID', '分辨率', '播放地址')
    foreach ($camera in (Get-Cameras)) {
        $proc = Get-CameraProcess $camera.name
        $state = if ($proc) { '运行中' } else { '已停止' }
        $procId = if ($proc) { $proc.Id } else { '-' }
        $size = if ($camera.type -eq 'rtsp' -and $camera.copy -ne $false) { '原流' } else { "$($camera.width)x$($camera.height)" }
        $url = "http://127.0.0.1:$($script:Cfg.mediaMtx.webrtcPort)/$($camera.name)"
        Write-Host ('{0,-10} {1,-8} {2,-8} {3,-18} {4}' -f $camera.name, $state, $procId, $size, $url)
    }
    if ((Get-Cameras).Count -eq 0) { Warn '（没有配置摄像头）' }
}

function Show-Urls {
    if ((Get-Cameras).Count -eq 0) { Warn '还没有配置摄像头'; return }
    foreach ($camera in (Get-Cameras)) {
        Write-Host "[$($camera.name)] $($camera.label)" -ForegroundColor White
        Info "  WebRTC: http://127.0.0.1:$($script:Cfg.mediaMtx.webrtcPort)/$($camera.name)"
        Info "  HLS   : http://127.0.0.1:$($script:Cfg.mediaMtx.hlsPort)/$($camera.name)/index.m3u8"
        Info "  局域网: http://<本机IP>:$($script:Cfg.mediaMtx.webrtcPort)/$($camera.name)"
    }
}

function Show-Devices {
    if (-not $script:Cfg.ffmpeg) { throw '找不到 ffmpeg.exe' }
    $devices = Get-VideoDevices $script:Cfg.ffmpeg
    if ($devices.Count -eq 0) {
        Warn '没有找到视频设备（或被其他程序占用）'
        return
    }
    Write-Host '本机视频设备：' -ForegroundColor White
    for ($i = 0; $i -lt $devices.Count; $i++) {
        Write-Host ("  [{0}] {1}" -f $i, $devices[$i])
    }
}

function Add-Camera {
    $cameraName = $Name
    if (-not $cameraName) { $cameraName = Read-Host '摄像头名称（英文/数字，如 cam2）' }
    $cameraName = $cameraName.Trim()
    if ($cameraName -notmatch '^[A-Za-z0-9_-]+$') { throw '名称只能包含字母、数字、下划线和短横线' }
    if (Get-Camera $cameraName) { throw "摄像头 $cameraName 已存在" }

    $cameraType = $Type
    if (-not $cameraType) {
        $cameraType = Read-Host '类型：dshow=本机/USB 摄像头，rtsp=IP 摄像头（默认 dshow）'
        if (-not $cameraType) { $cameraType = 'dshow' }
    }
    $cameraType = $cameraType.ToLower()
    if ($cameraType -notin @('dshow', 'rtsp')) { throw '类型只能是 dshow 或 rtsp' }

    $cameraSource = $Source
    if (-not $cameraSource) {
        if ($cameraType -eq 'dshow') {
            $devices = Get-VideoDevices $script:Cfg.ffmpeg
            if ($devices.Count -eq 0) { throw '没有找到视频设备' }
            Write-Host '可用设备：'
            for ($i = 0; $i -lt $devices.Count; $i++) { Write-Host ("  [{0}] {1}" -f $i, $devices[$i]) }
            $pick = Read-Host '输入设备序号或完整名称（默认 0）'
            if (-not $pick) { $pick = '0' }
            if ($pick -match '^\d+$') {
                $index = [int]$pick
                if ($index -lt 0 -or $index -ge $devices.Count) { throw '设备序号超出范围' }
                $cameraSource = $devices[$index]
            } else {
                $cameraSource = $pick
            }
        } else {
            $cameraSource = Read-Host 'RTSP 地址（如 rtsp://admin:密码@192.168.2.50:554/Streaming/Channels/101）'
        }
    }
    if (-not $cameraSource) { throw '视频源不能为空' }

    $cameraLabel = $Label
    if (-not $cameraLabel) {
        $cameraLabel = Read-Host "显示名称（默认 $cameraName）"
    }
    if (-not $cameraLabel) { $cameraLabel = $cameraName }

    $useCopy = $false
    if ($cameraType -eq 'rtsp') {
        if ($Copy) {
            $useCopy = $true
        } else {
            $copyAnswer = Read-Host '是否直接复制原流（H.264 建议 Y，不转码；默认 Y）'
            if ($copyAnswer -notmatch '^[nN]') { $useCopy = $true }
        }
    }

    $newCamera = [ordered]@{
        name = $cameraName
        label = $cameraLabel
        type = $cameraType
        source = $cameraSource
        width = $Width
        height = $Height
        fps = $Fps
        bitrate = $Bitrate
        copy = $useCopy
        enabled = $true
    }
    $script:Cfg.cameras = @(Get-Cameras) + $newCamera
    Save-Config
    Ok "已添加摄像头 $cameraName"

    if (-not $NoPause) {
        $startNow = Read-Host '现在启动吗？(Y/n)'
        if ($startNow -notmatch '^[nN]') { Start-Camera (Get-Camera $cameraName) }
    }
}

function Remove-Camera {
    $cameraName = $Name
    if (-not $cameraName) { $cameraName = Read-Host '要删除的摄像头名称' }
    $camera = Get-Camera $cameraName
    if (-not $camera) { throw "摄像头 $cameraName 不存在" }
    $answer = Read-Host "确认删除 $cameraName？(y/N)"
    if ($answer -notmatch '^[yY]') { Info '已取消'; return }
    Stop-Camera $cameraName
    $script:Cfg.cameras = @(Get-Cameras | Where-Object { $_.name -ne $cameraName })
    Save-Config
    Ok "已删除摄像头 $cameraName"
}

function Show-Menu {
    while ($true) {
        Clear-Host
        Write-Host '========================================' -ForegroundColor DarkCyan
        Write-Host '  智护库安 · 本地视频工具' -ForegroundColor Cyan
        Write-Host '========================================' -ForegroundColor DarkCyan
        Write-Host "配置：$ConfigPath"
        Write-Host ''
        Show-Status
        Write-Host ''
        Write-Host '  1. 启动全部摄像头'
        Write-Host '  2. 停止全部摄像头'
        Write-Host '  3. 启动单个摄像头'
        Write-Host '  4. 停止单个摄像头'
        Write-Host '  5. 新增摄像头'
        Write-Host '  6. 删除摄像头'
        Write-Host '  7. 列出本机摄像头'
        Write-Host '  8. 显示播放地址'
        Write-Host '  9. 打开配置目录'
        Write-Host '  0. 退出'
        Write-Host ''
        $choice = Read-Host '请选择'
        try {
            switch ($choice) {
                '1' { Start-All }
                '2' { Stop-All }
                '3' {
                    $cameraName = Read-Host '摄像头名称'
                    $camera = Get-Camera $cameraName
                    if (-not $camera) { throw "摄像头 $cameraName 不存在" }
                    Start-Camera $camera
                }
                '4' {
                    $cameraName = Read-Host '摄像头名称'
                    Stop-Camera $cameraName
                }
                '5' { Add-Camera }
                '6' { Remove-Camera }
                '7' { Show-Devices }
                '8' { Show-Urls }
                '9' { Start-Process explorer.exe $Root | Out-Null }
                '0' { return }
                default { Warn '无效选项' }
            }
        } catch {
            Fail $_.Exception.Message
        }
        if ($choice -ne '0') { Read-Host '按回车继续' | Out-Null }
    }
}

function Show-Help {
    @'
智护库安 · 本地视频工具

  .\zhka-video.ps1                进入菜单
  .\zhka-video.ps1 status         查看状态
  .\zhka-video.ps1 start          启动全部
  .\zhka-video.ps1 start -Name cam1
  .\zhka-video.ps1 stop           停止全部
  .\zhka-video.ps1 stop -Name cam1
  .\zhka-video.ps1 add            交互式新增
  .\zhka-video.ps1 add -Name cam2 -Type dshow -Source "USB Camera"
  .\zhka-video.ps1 add -Name gate -Type rtsp -Source "rtsp://..." -Copy -Label "闸门摄像头"
  .\zhka-video.ps1 remove -Name cam2
  .\zhka-video.ps1 devices        列出本机摄像头
  .\zhka-video.ps1 url            显示播放地址

配置和日志：%LOCALAPPDATA%\ZhkaVideo
'@ | Write-Host
}

try {
    Load-Config
    switch ($Command.ToLower()) {
        'menu' { Show-Menu }
        'start' {
            if ($Name) {
                $camera = Get-Camera $Name
                if (-not $camera) { throw "摄像头 $Name 不存在" }
                Start-Camera $camera
            } else { Start-All }
        }
        'stop' {
            if ($Name) { Stop-Camera $Name } else { Stop-All }
        }
        'restart' { Stop-All; Start-All }
        'status' { Show-Status }
        'list' {
            Get-Cameras | Format-Table name, label, type, source, enabled -AutoSize
        }
        'add' { Add-Camera }
        'remove' { Remove-Camera }
        'devices' { Show-Devices }
        'url' { Show-Urls }
        'help' { Show-Help }
        default { Show-Help }
    }
} catch {
    Fail $_.Exception.Message
    exit 1
}
