"""Shared validated contracts used by services, engines and HTTP responses."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    """Reject unknown fields and non-finite numbers at module boundaries."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TranscriptionOptions(Contract):
    start_seconds: float = Field(default=0, ge=0)
    end_seconds: float | None = Field(default=None, gt=0)
    language: Literal["fr", "en"] | None = None
    vad_filter: bool = True
    beam_size: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if self.end_seconds is not None and self.end_seconds <= self.start_seconds:
            raise ValueError("La fin doit être supérieure au début de la scène.")
        return self


class MediaInfo(Contract):
    duration_seconds: float = Field(gt=0)
    format_name: str
    audio_stream_index: int = Field(ge=0)
    audio_codec: str
    video_codec: str
    size_bytes: int = Field(gt=0)


class SceneRange(Contract):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("La scène doit avoir une durée positive.")
        return self

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


class Segment(Contract):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_segment(self) -> Self:
        self.text = self.text.strip()
        if not self.text or self.end <= self.start:
            raise ValueError("Un segment doit contenir du texte et avoir une durée positive.")
        return self


class ASRResult(Contract):
    segments: list[Segment]
    language: str
    language_probability: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if any(b.start < a.end for a, b in zip(self.segments, self.segments[1:], strict=False)):
            raise ValueError("Les segments doivent être chronologiques et sans chevauchement.")
        return self


class ProcessingMetrics(Contract):
    extraction_seconds: float = Field(ge=0)
    inference_seconds: float = Field(ge=0)
    audio_duration_seconds: float = Field(gt=0)
    rtf: float = Field(ge=0)


class TranscriptionResult(ASRResult):
    job_id: str
    source_filename: str
    source_duration_seconds: float = Field(gt=0)
    scene_start_seconds: float = Field(ge=0)
    scene_duration_seconds: float = Field(gt=0)
    model: str
    device: str
    compute_type: str
    vad_filter: bool
    beam_size: int
    metrics: ProcessingMetrics
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class JobStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ErrorDetail(Contract):
    category: str
    message: str


class JobView(Contract):
    id: str
    status: JobStatus
    stage: str
    original_filename: str
    options: TranscriptionOptions
    created_at: datetime
    updated_at: datetime
    result: TranscriptionResult | None = None
    error: ErrorDetail | None = None
