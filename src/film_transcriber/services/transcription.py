"""Orchestrate extraction, local inference, timing and export publication."""

import logging
from collections.abc import Callable
from pathlib import Path
from time import perf_counter

from film_transcriber.asr.base import ASREngine
from film_transcriber.core.config import Settings
from film_transcriber.core.errors import AppError
from film_transcriber.core.models import (
    ProcessingMetrics,
    TranscriptionOptions,
    TranscriptionResult,
)
from film_transcriber.exporters.json_exporter import render_json
from film_transcriber.exporters.srt import render_srt
from film_transcriber.exporters.txt import render_txt
from film_transcriber.services.media import MediaService

logger = logging.getLogger(__name__)


class TranscriptionService:
    """A blocking pipeline executed by a bounded worker or explicitly by the CLI."""

    def __init__(self, settings: Settings, media: MediaService, engine: ASREngine) -> None:
        self.settings = settings
        self.media = media
        self.engine = engine

    def process(
        self,
        job_id: str,
        source: Path,
        filename: str,
        options: TranscriptionOptions,
        on_stage: Callable[[str], None],
    ) -> TranscriptionResult:
        """Return only once inference and every export have completed successfully."""
        audio = source.with_name("audio.wav")
        try:
            on_stage("validating")
            info = self.media.inspect(source)
            scene = self.media.select_scene(info, options)
            on_stage("extracting")
            before = perf_counter()
            duration = self.media.extract(source, audio, info, scene)
            extraction_seconds = perf_counter() - before
            on_stage("transcribing")
            before = perf_counter()
            transcription = self.engine.transcribe(audio, options)
            inference_seconds = perf_counter() - before
            if any(segment.end > duration + 0.1 for segment in transcription.segments):
                raise AppError("invalid_segments", "Les timestamps dépassent la durée audio.")
            metrics = ProcessingMetrics(
                extraction_seconds=extraction_seconds,
                inference_seconds=inference_seconds,
                audio_duration_seconds=duration,
                rtf=inference_seconds / duration,
            )
            result = TranscriptionResult(
                **transcription.model_dump(),
                job_id=job_id,
                source_filename=filename,
                source_duration_seconds=info.duration_seconds,
                scene_start_seconds=scene.start_seconds,
                scene_duration_seconds=duration,
                model=self.settings.model_name,
                device=self.settings.device,
                compute_type=self.settings.compute_type,
                vad_filter=options.vad_filter,
                beam_size=options.beam_size,
                metrics=metrics,
            )
            on_stage("exporting")
            for extension, renderer in (
                ("txt", render_txt),
                ("srt", render_srt),
                ("json", render_json),
            ):
                temporary = source.with_name(f"transcript.{extension}.tmp")
                temporary.write_text(renderer(result), encoding="utf-8")
                temporary.replace(source.with_name(f"transcript.{extension}"))
            logger.info(
                "pipeline_completed",
                extra={
                    "job_id": job_id,
                    "stage": "completed",
                    "status": "COMPLETED",
                    "model": result.model,
                    **metrics.model_dump(),
                },
            )
            return result
        finally:
            audio.unlink(missing_ok=True)
            for temporary in source.parent.glob("transcript.*.tmp"):
                temporary.unlink(missing_ok=True)
