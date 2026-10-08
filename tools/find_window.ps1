# 按窗口标题查找窗口并输出物理坐标到 stdout
param([string]$title = "OCRTest")
Add-Type -MemberDefinition @"
public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
[DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern System.IntPtr FindWindow(string lpClassName, string lpWindowName);
[DllImport("user32.dll")] public static extern bool GetWindowRect(System.IntPtr hWnd, out RECT rect);
"@ -Name W32v4 -Namespace W
$h = [W.W32v4]::FindWindow($null, $title)
$r = New-Object W.RECT
$ok = [W.W32v4]::GetWindowRect($h, [ref]$r)
Write-Output "$ok $($r.Left) $($r.Top) $($r.Right) $($r.Bottom)"
