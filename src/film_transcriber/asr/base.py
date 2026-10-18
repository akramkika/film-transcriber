"""Stable engine interface, independent of the selected ASR implementation."""

from abc import ABC, abstractmethod
from pathlib import Path

from film_transcriber.core.models import ASRResult, TranscriptionOptions


class ASREngine(ABC):
    @abstractmethod
    def transcribe(self, audio: Path, options: TranscriptionOptions) -> ASRResult:
        """Complete inference and return scene-relative, chronological segments."""
        raise NotImplementedError
