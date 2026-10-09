Add-Type -AssemblyName System.Drawing
$b = New-Object System.Drawing.Bitmap(2560, 1600)
$g = [System.Drawing.Graphics]::FromImage($b)
$g.CopyFromScreen(0, 0, 0, 0, $b.Size)
$b.Save("D:\翻译插件\tools\screen_dbg.png")
$g.Dispose(); $b.Dispose()
Write-Output "saved"
