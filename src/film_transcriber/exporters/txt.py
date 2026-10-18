"""Plain transcript export."""

from film_transcriber.core.models import TranscriptionResult


def render_txt(result: TranscriptionResult) -> str:
    """Render one nonempty segment per line, preserving Unicode."""
    lines = [segment.text.strip() for segment in result.segments if segment.text.strip()]
    return "\n".join(lines) + ("\n" if lines else "")
