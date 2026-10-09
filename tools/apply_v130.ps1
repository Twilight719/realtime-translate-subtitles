# 解压 v1.3.0 并覆盖更新 C:\rtbuild\dist\实时翻译字幕（保留 config.yaml / 日志 / models）
$ErrorActionPreference = "Stop"
$tmp = "C:\rtbuild\dist\_v130_extract"
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
Expand-Archive -Path "C:\rtbuild\dist\realtime-translate-subtitles-v1.3.0-windows-x64.zip" -DestinationPath $tmp
$src = Get-ChildItem $tmp -Directory | Select-Object -First 1
Write-Output "extracted folder: $($src.Name)"
robocopy "$($src.FullName)" "C:\rtbuild\dist\实时翻译字幕" /E /IS /XF config.yaml app.log app.log.1 app.log.2 /XD models /NFL /NDL /NJH /NJS | Out-Null
Remove-Item -Recurse -Force $tmp
Write-Output "updated"
