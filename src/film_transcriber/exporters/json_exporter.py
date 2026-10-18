"""Complete machine-readable export, including source offset and timings."""

from film_transcriber.core.models import TranscriptionResult


def render_json(result: TranscriptionResult) -> str:
    """Serialize the public contract with Unicode and ISO datetime values."""
    return result.model_dump_json(indent=2) + "\n"
