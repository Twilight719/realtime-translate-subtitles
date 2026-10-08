# 模拟鼠标拖拽：mouse_drag.ps1 x1 y1 x2 y2（Cursor.Position 移动 + mouse_event 按键）
param([int]$x1, [int]$y1, [int]$x2, [int]$y2)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -MemberDefinition @"
[DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, int dx, int dy, uint dwData, System.UIntPtr dwExtraInfo);
"@ -Name U32v2 -Namespace W
[System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point($x1, $y1)
Start-Sleep -Milliseconds 300
[W.U32v2]::mouse_event(0x0002, 0, 0, 0, [System.UIntPtr]::Zero)  # LEFTDOWN
Start-Sleep -Milliseconds 200
for ($i = 1; $i -le 25; $i++) {
    $x = $x1 + [int](($x2 - $x1) * $i / 25)
    $y = $y1 + [int](($y2 - $y1) * $i / 25)
    [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point($x, $y)
    Start-Sleep -Milliseconds 30
}
Start-Sleep -Milliseconds 200
[W.U32v2]::mouse_event(0x0004, 0, 0, 0, [System.UIntPtr]::Zero)  # LEFTUP
Write-Output ("drag done, cursor at " + [System.Windows.Forms.Cursor]::Position)
