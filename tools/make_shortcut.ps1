$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut([IO.Path]::Combine($env:USERPROFILE, 'Desktop', '实时翻译字幕.lnk'))
$sc.TargetPath = 'C:\rtbuild\dist\实时翻译字幕\实时翻译字幕.exe'
$sc.WorkingDirectory = 'C:\rtbuild\dist\实时翻译字幕'
$sc.IconLocation = 'C:\rtbuild\dist\实时翻译字幕\实时翻译字幕.exe,0'
$sc.Save()
Write-Output "shortcut created"
