# 智护库安 · 本地视频工具

本机摄像头 / IP 摄像头推流到本机 MediaMTX，局域网用浏览器看 WebRTC。
不做开机自启，只做手动启停。

## 依赖

已经装好可跳过（winget）：

```powershell
winget install Gyan.FFmpeg
winget install bluenviron.mediamtx
```

## 使用

双击 `zhka-video.cmd` 进菜单，或者在 PowerShell 里：

```powershell
# 查看状态
.\zhka-video.ps1 status

# 启动 / 停止全部
.\zhka-video.ps1 start
.\zhka-video.ps1 stop

# 单个
.\zhka-video.ps1 start -Name cam1
.\zhka-video.ps1 stop -Name cam1

# 本机 / USB 摄像头
.\zhka-video.ps1 devices
.\zhka-video.ps1 add -Name cam2 -Type dshow -Source "USB Camera"

# IP 摄像头（H.264 建议 -Copy，不转码）
.\zhka-video.ps1 add -Name gate -Type rtsp `
  -Source "rtsp://admin:密码@192.168.2.50:554/Streaming/Channels/101" `
  -Copy -Label "闸门摄像头"

# 删除
.\zhka-video.ps1 remove -Name cam2

# 播放地址
.\zhka-video.ps1 url
```

## 播放地址

- WebRTC：`http://127.0.0.1:8889/<名称>`
- HLS 备用：`http://127.0.0.1:8888/<名称>/index.m3u8`
- 局域网：把 `127.0.0.1` 换成电脑的局域网 IP

例：`http://192.168.2.7:8889/cam1`

## 配置和日志

- 配置：`%LOCALAPPDATA%\ZhkaVideo\config.json`
- 日志：`%LOCALAPPDATA%\ZhkaVideo\logs\`
- 运行 PID：`%LOCALAPPDATA%\ZhkaVideo\run\`

首次运行会自动探测 `ffmpeg.exe`、`mediamtx.exe`，并把第一个视频设备建成 `cam1`。
换电脑或换摄像头后，改 `config.json` 或重新 `add` 即可。

## 局域网访问

别人要访问，需要在管理员 PowerShell 放行防火墙：

```powershell
New-NetFirewallRule -DisplayName "MediaMTX WebRTC" -Direction Inbound -Protocol TCP -LocalPort 8889 -Action Allow
New-NetFirewallRule -DisplayName "MediaMTX WebRTC UDP" -Direction Inbound -Protocol UDP -LocalPort 8189 -Action Allow
```

## 说明

- 每个 USB 摄像头一路 libx264 编码，会吃 CPU；IP 摄像头用 `-Copy` 几乎不耗 CPU。
- H.265 的 IP 摄像头 WebRTC 播不了，请在摄像头后台开 H.264 子码流。
- `stop` 只停摄像头，MediaMTX 会继续留着（占用很小）；要连 MediaMTX 一起停，直接 `Stop-Process -Name mediamtx`。
