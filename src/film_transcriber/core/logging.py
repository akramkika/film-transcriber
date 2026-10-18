"""Structured pipeline logs that never include transcript or audio contents."""

import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "time": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        for field in (
            "job_id",
            "stage",
            "status",
            "category",
            "model",
            "extraction_seconds",
            "inference_seconds",
            "audio_duration_seconds",
            "rtf",
            "exception_type",
        ):
            if hasattr(record, field):
                entry[field] = getattr(record, field)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging() -> None:
    """Configure only the application logger, preserving host logging settings."""
    logger = logging.getLogger("film_transcriber")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
