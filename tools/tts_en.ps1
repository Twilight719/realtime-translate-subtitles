# 用系统 TTS 朗读英文句子（经默认扬声器输出，loopback 可捕获）
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = -1
$synth.Volume = 100
$synth.Speak("Hello, this is a test of the real time translation subtitle system.")
