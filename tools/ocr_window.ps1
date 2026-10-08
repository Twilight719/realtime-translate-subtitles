# 全屏显示大字（供 OCR 截图测试），120 秒后自动关闭
Add-Type -AssemblyName PresentationFramework
[xml]$xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        Title="OCRTest" WindowState="Maximized" Topmost="True" Background="White">
  <TextBlock Text="你好世界，这是截图翻译测试" FontSize="120" FontFamily="Microsoft YaHei"
             Foreground="Black" VerticalAlignment="Center" HorizontalAlignment="Center"/>
</Window>
"@
$reader = New-Object System.Xml.XmlNodeReader $xaml
$win = [Windows.Markup.XamlReader]::Load($reader)
$timer = New-Object System.Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromSeconds(120)
$timer.Add_Tick({ $win.Close() })
$timer.Start()
$win.ShowDialog() | Out-Null
