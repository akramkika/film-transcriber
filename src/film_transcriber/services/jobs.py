"""Bounded uploads and jobs, with explicit memory-only state and local storage."""

import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from threading import RLock
from typing import BinaryIO
from uuid import UUID, uuid4

from film_transcriber.core.config import Settings
from film_transcriber.core.errors import AppError
from film_transcriber.core.models import ErrorDetail, JobStatus, JobView, TranscriptionOptions
from film_transcriber.services.transcription import TranscriptionService

logger = logging.getLogger(__name__)
EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi"}


@dataclass
class JobRecord:
    view: JobView
    source: Path


class JobManager:
    """Own uploads, transitions and deletion; no processing runs on the event loop."""

    def __init__(self, settings: Settings, pipeline: TranscriptionService) -> None:
        self.settings = settings
        self.pipeline = pipeline
        self.root = settings.data_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, JobRecord] = {}
        self._lock = RLock()
        self._reserved = 0
        self._closed = False
        self._executor = ThreadPoolExecutor(
            max_workers=settings.max_workers, thread_name_prefix="transcription"
        )

    def submit_upload(
        self, stream: BinaryIO, filename: str | None, options: TranscriptionOptions
    ) -> JobView:
        """Copy an upload with a hard byte cap, then enqueue it for validation."""
        original = PureWindowsPath(filename or "video").name
        original = "".join(char for char in original if char.isprintable())[:200]
        extension = Path(original).suffix.lower()
        if extension not in EXTENSIONS:
            raise AppError("unsupported_extension", "Choisissez une vidéo MP4, MKV, MOV ou AVI.")
        with self._lock:
            if self._closed:
                raise AppError("shutting_down", "L'application est en cours d'arrêt.", 503)
            if len(self._jobs) + self._reserved >= self.settings.max_jobs:
                raise AppError(
                    "queue_full", "Supprimez un ancien traitement avant de continuer.", 429
                )
            self._reserved += 1
        job_id = str(uuid4())
        directory = self.root / job_id
        source = directory / f"source{extension}"
        try:
            directory.mkdir()
            total = 0
            with source.open("xb") as target:
                while chunk := stream.read(1024 * 1024):
                    total += len(chunk)
                    if total > self.settings.max_upload_bytes:
                        raise AppError(
                            "file_too_large", "La vidéo dépasse la taille autorisée.", 413
                        )
                    target.write(chunk)
            if total == 0:
                raise AppError("empty_file", "Le fichier vidéo est vide.")
            now = datetime.now(UTC)
            view = JobView(
                id=job_id,
                status=JobStatus.PENDING,
                stage="queued",
                original_filename=original,
                options=options,
                created_at=now,
                updated_at=now,
            )
            with self._lock:
                if self._closed:
                    raise AppError("shutting_down", "L'application est en cours d'arrêt.", 503)
                self._jobs[job_id] = JobRecord(view=view, source=source)
                try:
                    self._executor.submit(self._run, job_id)
                except RuntimeError as exc:
                    del self._jobs[job_id]
                    raise AppError(
                        "shutting_down", "L'application est en cours d'arrêt.", 503
                    ) from exc
                return view.model_copy(deep=True)
        except BaseException:
            if directory.exists():
                shutil.rmtree(directory)
            raise
        finally:
            with self._lock:
                self._reserved -= 1

    def _record(self, job_id: str) -> JobRecord:
        try:
            if str(UUID(job_id)) != job_id:
                raise ValueError
        except ValueError as exc:
            raise AppError("job_not_found", "Traitement introuvable.", 404) from exc
        record = self._jobs.get(job_id)
        if record is None:
            raise AppError("job_not_found", "Traitement introuvable.", 404)
        return record

    def get(self, job_id: str) -> JobView:
        with self._lock:
            return self._record(job_id).view.model_copy(deep=True)

    def list_jobs(self) -> list[JobView]:
        with self._lock:
            return [record.view.model_copy(deep=True) for record in reversed(self._jobs.values())]

    def media_path(self, job_id: str) -> Path:
        with self._lock:
            record = self._record(job_id)
            if record.view.status != JobStatus.COMPLETED:
                raise AppError("media_not_ready", "La vidéo sera disponible après validation.", 409)
            return record.source

    def export_path(self, job_id: str, extension: str) -> Path:
        if extension not in {"txt", "srt", "json"}:
            raise AppError("unknown_export", "Format d'export inconnu.", 404)
        with self._lock:
            record = self._record(job_id)
            if record.view.status != JobStatus.COMPLETED:
                raise AppError(
                    "result_not_ready", "La transcription n'est pas encore disponible.", 409
                )
            return record.source.with_name(f"transcript.{extension}")

    def delete(self, job_id: str) -> None:
        with self._lock:
            record = self._record(job_id)
            if record.view.status in {JobStatus.PENDING, JobStatus.PROCESSING}:
                raise AppError(
                    "job_active", "Attendez la fin du traitement pour le supprimer.", 409
                )
            directory = record.source.parent.resolve()
            if directory.parent != self.root or directory.name != job_id:
                raise AppError("unsafe_path", "Suppression refusée : chemin invalide.", 400)
            shutil.rmtree(directory)
            del self._jobs[job_id]

    def _run(self, job_id: str) -> None:
        with self._lock:
            record = self._record(job_id)
            record.view.status = JobStatus.PROCESSING
        try:
            result = self.pipeline.process(
                job_id,
                record.source,
                record.view.original_filename,
                record.view.options,
                lambda stage: self._stage(job_id, stage),
            )
            with self._lock:
                record.view.result = result
                record.view.status = JobStatus.COMPLETED
                record.view.stage = "completed"
                record.view.updated_at = datetime.now(UTC)
        except Exception as exc:
            if isinstance(exc, AppError):
                error = ErrorDetail(category=exc.category, message=exc.message)
            elif isinstance(exc, MemoryError):
                error = ErrorDetail(category="out_of_memory", message="Mémoire insuffisante.")
            else:
                error = ErrorDetail(
                    category="processing_failed",
                    message="Le traitement a échoué. Consultez les logs.",
                )
            with self._lock:
                record.view.error = error
                record.view.status = JobStatus.FAILED
                record.view.stage = "failed"
                record.view.updated_at = datetime.now(UTC)
            logger.error(
                "pipeline_failed",
                extra={
                    "job_id": job_id,
                    "stage": "failed",
                    "status": "FAILED",
                    "category": error.category,
                    "exception_type": type(exc).__name__,
                },
            )

    def _stage(self, job_id: str, stage: str) -> None:
        with self._lock:
            record = self._record(job_id)
            record.view.stage = stage
            record.view.updated_at = datetime.now(UTC)
        logger.info(
            "pipeline_stage", extra={"job_id": job_id, "stage": stage, "status": "PROCESSING"}
        )

    def shutdown(self) -> None:
        """Finish accepted jobs before graceful shutdown; no state survives restart."""
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=True)
