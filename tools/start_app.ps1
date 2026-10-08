# 启动被测程序
$exe = "C:\rtbuild\dist\实时翻译字幕\实时翻译字幕.exe"
Start-Process -FilePath $exe -WorkingDirectory (Split-Path $exe)
