# Makes fixtures/uploads/voice-note-sharma.wav (batch 7 plan, D22): a Hinglish
# voice note spoken by Windows' built-in speech synthesiser (System.Speech, no
# new dependency). Only English voices ship with Windows here (Hazel, en-GB;
# Zira, en-US), so the Hindi words are read with English phonetics. Whether a
# model can transcribe it is shown only by an authorised live eval run; the
# fixture AI answers from its canned transcript in fixtures/ai_replies.json.
#
#   powershell -ExecutionPolicy Bypass -File scripts/make_voice_fixture.ps1
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$text = "Sharma Packaging ka bill, dedh lakh rupaye, paanch November tak dena hai."
$out = Join-Path (Split-Path -Parent $PSScriptRoot) "fixtures\uploads\voice-note-sharma.wav"
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voice = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -eq "en-GB" } | Select-Object -First 1
    if ($voice) { $s.SelectVoice($voice.VoiceInfo.Name) }
    $s.Rate = -2  # a little slower than normal, for the place names and numbers
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $s.SetOutputToWaveFile($out, $format)
    $s.Speak($text)
} finally {
    $s.Dispose()
}
Write-Output "wrote $out with voice $($voice.VoiceInfo.Name)"
