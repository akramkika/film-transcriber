"""SubRip export with scene-relative milliseconds."""

import math

from film_transcriber.core.models import TranscriptionResult


def _timestamp(milliseconds: int) -> str:
    seconds, millis = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def render_srt(result: TranscriptionResult) -> str:
    """Reject inconsistent times and avoid empty or zero-length subtitle cues."""
    blocks: list[str] = []
    previous_end = 0.0
    for segment in result.segments:
        if (
            not math.isfinite(segment.start)
            or not math.isfinite(segment.end)
            or segment.start < previous_end
            or segment.end <= segment.start
        ):
            raise ValueError("Les segments SRT doivent être chronologiques et de durée positive.")
        previous_end = segment.end
        text = " ".join(segment.text.split())
        if not text:
            continue
        start = int(segment.start * 1000 + 0.5)
        end = max(start + 1, int(segment.end * 1000 + 0.5))
        blocks.append(f"{len(blocks) + 1}\n{_timestamp(start)} --> {_timestamp(end)}\n{text}")
    return "\n\n".join(blocks) + ("\n\n" if blocks else "")
