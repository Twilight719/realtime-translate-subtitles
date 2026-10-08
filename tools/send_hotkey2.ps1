# 用 keybd_event 注入全局热键（不依赖前台窗口焦点）
param([string]$hotkey = "alt+t")
Add-Type -MemberDefinition @"
[DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, System.UIntPtr dwExtraInfo);
"@ -Name Kbd -Namespace W
$VK = @{ "alt" = 0x12; "ctrl" = 0x11; "shift" = 0x10 }
$KEYUP = 0x0002
$parts = $hotkey.ToLower().Split("+")
$mods = $parts | Select-Object -SkipLast 1
$key = [byte][char]($parts[-1].ToUpper()[0])
foreach ($m in $mods) { [W.Kbd]::keybd_event([byte]$VK[$m], 0, 0, [System.UIntPtr]::Zero) }
Start-Sleep -Milliseconds 60
[W.Kbd]::keybd_event($key, 0, 0, [System.UIntPtr]::Zero)
Start-Sleep -Milliseconds 60
[W.Kbd]::keybd_event($key, 0, $KEYUP, [System.UIntPtr]::Zero)
foreach ($m in $mods) { [W.Kbd]::keybd_event([byte]$VK[$m], 0, $KEYUP, [System.UIntPtr]::Zero) }
