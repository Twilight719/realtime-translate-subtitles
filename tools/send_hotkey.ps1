# 发送全局热键：send_hotkey.ps1 "alt+t"（支持 alt/ctrl/shift/win + 单字符）
param([string]$hotkey = "alt+t")
Add-Type -AssemblyName System.Windows.Forms
$mods = ""
foreach ($p in $hotkey.ToLower().Split("+") | Select-Object -SkipLast 1) {
    switch ($p) {
        "alt"   { $mods += "%" }
        "ctrl"  { $mods += "^" }
        "shift" { $mods += "+" }
    }
}
$key = ($hotkey -split "\+")[-1].ToUpper()
[System.Windows.Forms.SendKeys]::SendWait($mods + $key)
