# 验证 SetCursorPos/GetCursorPos 是否正常工作
Add-Type -MemberDefinition @"
public struct POINT { public int X; public int Y; }
[DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
[DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
"@ -Name W32v5 -Namespace W
$p = New-Object W.POINT
[W.W32v5]::GetCursorPos([ref]$p) | Out-Null
Write-Output "before: $($p.X),$($p.Y)"
$r = [W.W32v5]::SetCursorPos(800, 600)
Start-Sleep -Milliseconds 300
[W.W32v5]::GetCursorPos([ref]$p) | Out-Null
Write-Output "set result: $r  after: $($p.X),$($p.Y)"
