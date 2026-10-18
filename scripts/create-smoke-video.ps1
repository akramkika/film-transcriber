# Windows-only, entirely local synthetic speech/video for a real ASR smoke test.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$sampleDir = Join-Path $projectRoot 'artifacts/smoke'
New-Item -ItemType Directory -Path $sampleDir -Force | Out-Null
Add-Type -AssemblyName System.Speech
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $french = $voice.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'fr-*' } | Select-Object -First 1
    if ($french) {
        $voice.SelectVoice($french.VoiceInfo.Name)
        $speech = 'Bonjour. Ceci est une video de test generee sur cet ordinateur. Nous verifions que la transcription fonctionne sans service externe. La video reste visible a gauche et les dialogues apparaissent a droite. Chaque phrase suit la lecture. Nous pouvons faire une pause, revenir en arriere et reprendre la scene. Les sous-titres sont disponibles dans plusieurs formats. Ce test est maintenant termine.'
    } else {
        $speech = 'Hello. This is a test video generated on this computer. We are checking that transcription works without an external service. The video stays visible on the left and the dialogue appears on the right. Every sentence follows playback. We can pause, go back, and resume the scene. Subtitles are available in several formats. This test is now complete.'
    }
    $voice.SetOutputToWaveFile((Join-Path $sampleDir 'speech.wav'))
    $voice.Speak($speech)
} finally {
    $voice.Dispose()
}
$ffmpeg = Join-Path $projectRoot '.tools/ffmpeg/bin/ffmpeg.exe'
if (-not (Test-Path -LiteralPath $ffmpeg)) { $ffmpeg = (Get-Command ffmpeg -ErrorAction Stop).Source }
& $ffmpeg -hide_banner -loglevel error -y -f lavfi -i 'color=c=0x162d29:s=960x540:r=25' -i (Join-Path $sampleDir 'speech.wav') -af 'adelay=2000:all=1,apad=pad_dur=2' -c:v libx264 -preset ultrafast -pix_fmt yuv420p -c:a aac -shortest -movflags +faststart (Join-Path $sampleDir 'scene-test.mp4')
if ($LASTEXITCODE -ne 0) { throw 'Synthetic video generation failed.' }
Write-Output ('Video de test locale : ' + (Join-Path $sampleDir 'scene-test.mp4'))
