"""Lazy, locally cached faster-whisper inference without implicit downloads."""

import math
import threading
import wave
from pathlib import Path
from typing import Any

from film_transcriber.asr.base import ASREngine
from film_transcriber.core.config import Settings
from film_transcriber.core.errors import AppError
from film_transcriber.core.models import ASRResult, Segment, TranscriptionOptions


def resolve_model_path(settings: Settings) -> Path:
    """Use a configured local directory or an already downloaded HF cache snapshot."""
    if settings.model_path is not None:
        path = settings.model_path
    else:
        from faster_whisper.utils import download_model

        try:
            path = Path(
                download_model(
                    settings.model_name,
                    cache_dir=str(settings.model_cache_dir),
                    local_files_only=True,
                )
            )
        except (OSError, ValueError) as exc:
            raise AppError(
                "model_missing",
                "Le modèle local est absent. Exécutez d'abord la commande download-model.",
                503,
            ) from exc
    # Missing tokenizer.json can cause third-party code to request a fallback tokenizer.
    if any(not (path / name).is_file() for name in ("model.bin", "config.json", "tokenizer.json")):
        raise AppError(
            "model_missing",
            "Le modèle local est absent ou incomplet. Exécutez la commande download-model.",
            503,
        )
    return path.resolve()


def _create_model(path: Path, settings: Settings) -> Any:
    from faster_whisper import WhisperModel

    return WhisperModel(
        str(path),
        device=settings.device,
        compute_type=settings.compute_type,
        cpu_threads=settings.cpu_threads,
        num_workers=1,
        local_files_only=True,
    )


def _audio_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as audio:
            if (
                audio.getnchannels() != 1
                or audio.getsampwidth() != 2
                or audio.getframerate() != 16000
                or audio.getnframes() <= 0
            ):
                raise ValueError("invalid audio")
            return audio.getnframes() / audio.getframerate()
    except (OSError, EOFError, ValueError, wave.Error) as exc:
        raise AppError("invalid_audio", "Le fichier audio WAV est vide ou invalide.") from exc


class FasterWhisperEngine(ASREngine):
    """One lazy model per injected engine, with serialized access to inference."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: Any = None
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    def _load_model(self) -> Any:
        with self._load_lock:
            if self._model is None:
                self._model = _create_model(resolve_model_path(self.settings), self.settings)
            return self._model

    def transcribe(self, audio: Path, options: TranscriptionOptions) -> ASRResult:
        duration = _audio_duration(audio)
        try:
            with self._inference_lock:
                model = self._load_model()
                raw_segments, info = model.transcribe(
                    str(audio),
                    language=options.language,
                    task="transcribe",
                    beam_size=options.beam_size,
                    vad_filter=options.vad_filter,
                    word_timestamps=False,
                    condition_on_previous_text=False,
                )
                segments: list[Segment] = []
                # Iterating to exhaustion is essential: faster-whisper performs lazy inference.
                for raw in raw_segments:
                    text = " ".join(str(raw.text).split())
                    start, end = float(raw.start), float(raw.end)
                    if not math.isfinite(start) or not math.isfinite(end):
                        raise ValueError("invalid ASR timestamp")
                    start = max(0.0, start, segments[-1].end if segments else 0.0)
                    end = min(duration, end)
                    if text and end > start:
                        segments.append(Segment(start=start, end=end, text=text))
                return ASRResult(
                    segments=segments,
                    language=info.language,
                    language_probability=info.language_probability,
                )
        except AppError:
            raise
        except MemoryError as exc:
            raise AppError(
                "out_of_memory",
                "Mémoire insuffisante. Fermez des applications ou utilisez tiny.",
                503,
            ) from exc
        except Exception as exc:
            # Error text is used only for categorization, never returned or logged.
            message = str(exc).lower()
            if any(token in message for token in ("out of memory", "bad_alloc", "cannot allocate")):
                raise AppError(
                    "out_of_memory",
                    "Mémoire insuffisante pour le modèle de transcription.",
                    503,
                ) from exc
            raise AppError(
                "asr_failed",
                "La transcription a échoué. Vérifiez le modèle local et sa configuration.",
                500,
            ) from exc
