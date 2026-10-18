"""Diagnose only the generated smoke sample, never a user's private media."""

import traceback
from pathlib import Path

from film_transcriber.asr.faster_whisper import FasterWhisperEngine
from film_transcriber.core.config import Settings
from film_transcriber.core.models import TranscriptionOptions
from film_transcriber.services.media import MediaService

root = Path("artifacts/smoke")
settings = Settings()
media = MediaService(settings)
source = root / "scene-test.mp4"
options = TranscriptionOptions(start_seconds=2)
info = media.inspect(source)
scene = media.select_scene(info, options)
media.extract(source, root / "audio.wav", info, scene)
try:
    result = FasterWhisperEngine(settings).transcribe(root / "audio.wav", options)
    print(f"ASR OK: {len(result.segments)} segments, language={result.language}")
except Exception:
    (root / "asr-diagnostic.txt").write_text(traceback.format_exc(), encoding="utf-8")
    print("See artifacts/smoke/asr-diagnostic.txt")
    raise SystemExit(1) from None
