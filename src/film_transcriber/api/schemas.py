"""Convert form fields to the shared validated domain contract."""

from pydantic import ValidationError

from film_transcriber.core.errors import AppError
from film_transcriber.core.models import TranscriptionOptions


def parse_options(
    start_seconds: float, end_seconds: str, language: str, vad_filter: bool, beam_size: int
) -> TranscriptionOptions:
    try:
        return TranscriptionOptions.model_validate(
            {
                "start_seconds": start_seconds,
                "end_seconds": end_seconds or None,
                "language": None if language == "auto" else language,
                "vad_filter": vad_filter,
                "beam_size": beam_size,
            }
        )
    except ValidationError as exc:
        raise AppError(
            "invalid_options", "Vérifiez la plage, la langue et les paramètres."
        ) from exc
