"""Inspect local containers and extract bounded mono audio with FFmpeg."""

import json
import math
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any

from film_transcriber.core.config import Settings
from film_transcriber.core.errors import AppError
from film_transcriber.core.models import MediaInfo, SceneRange, TranscriptionOptions

_FORMATS = "mov,matroska,avi"


def resolve_binary(configured: str) -> str | None:
    """Resolve an explicit executable, PATH entry, or the project's local tools."""
    found = shutil.which(configured)
    if found:
        return found
    path = Path(configured)
    if path.is_file():
        return str(path.resolve())
    if path.name != configured:
        return None
    for name in (configured, f"{configured}.exe"):
        candidate = Path.cwd() / ".tools" / "ffmpeg" / "bin" / name
        if candidate.is_file():
            return str(candidate.resolve())
    return None


class MediaService:
    """All subprocesses are bounded, argument-based, and restricted to local inputs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _run(self, configured: str, arguments: list[str], stage: str) -> str:
        binary = resolve_binary(configured)
        if binary is None:
            raise AppError(
                "ffmpeg_missing",
                "FFmpeg et ffprobe doivent être installés. Consultez la commande doctor.",
                503,
            )
        try:
            completed = subprocess.run(
                [binary, *arguments],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.settings.process_timeout_seconds,
                check=True,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AppError("media_timeout", f"Le délai maximal de {stage} est dépassé.") from exc
        except subprocess.CalledProcessError as exc:
            # FFmpeg stderr can contain embedded metadata and private filenames.
            raise AppError(
                "invalid_media", f"Échec de {stage} : média invalide ou codec non pris en charge."
            ) from exc
        except OSError as exc:
            raise AppError(
                "ffmpeg_unavailable", "Impossible d'exécuter FFmpeg ou ffprobe.", 503
            ) from exc
        return completed.stdout

    def inspect(self, path: Path) -> MediaInfo:
        """Require a real supported video container, video stream, and usable audio."""
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise AppError("invalid_media", "Le fichier vidéo est inaccessible.") from exc
        if size <= 0:
            raise AppError("empty_file", "Le fichier vidéo est vide.")
        if size > self.settings.max_upload_bytes:
            raise AppError(
                "file_too_large", "Le fichier dépasse la taille maximale autorisée.", 413
            )
        output = self._run(
            self.settings.ffprobe_bin,
            [
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-format_whitelist",
                _FORMATS,
                "-show_entries",
                "format=format_name,duration:stream=index,codec_type,codec_name,width,height,"
                "sample_rate,channels,duration:stream_disposition=attached_pic",
                "-of",
                "json",
                "-i",
                str(path.resolve()),
            ],
            "l'inspection du média",
        )
        try:
            payload = json.loads(output)
            metadata = payload["format"]
            format_name = str(metadata["format_name"])
            if not set(format_name.split(",")).intersection(_FORMATS.split(",")):
                raise ValueError("unsupported container")
            streams: list[dict[str, Any]] = payload["streams"]
            video = next(
                (
                    item
                    for item in streams
                    if item.get("codec_type") == "video"
                    and int(item.get("width", 0)) > 0
                    and int(item.get("height", 0)) > 0
                    and item.get("codec_name") not in (None, "unknown")
                    and not item.get("disposition", {}).get("attached_pic", 0)
                ),
                None,
            )
            if video is None:
                raise AppError("no_video", "Le fichier ne contient aucune piste vidéo exploitable.")
            audio = next(
                (
                    item
                    for item in streams
                    if item.get("codec_type") == "audio"
                    and item.get("codec_name") not in (None, "unknown")
                    and int(item.get("channels", 0)) > 0
                    and int(item.get("sample_rate", 0)) > 0
                ),
                None,
            )
            if audio is None:
                raise AppError("no_audio", "Le fichier ne contient aucune piste audio exploitable.")
            duration = float(metadata.get("duration", video.get("duration", 0)))
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError("invalid duration")
            return MediaInfo(
                duration_seconds=duration,
                format_name=format_name,
                audio_stream_index=int(audio["index"]),
                audio_codec=str(audio["codec_name"]),
                video_codec=str(video["codec_name"]),
                size_bytes=size,
            )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise AppError(
                "invalid_media", "Le conteneur vidéo ou sa durée ne sont pas valides."
            ) from exc

    def select_scene(self, info: MediaInfo, options: TranscriptionOptions) -> SceneRange:
        """Validate bounds against the source; timestamps remain relative to this scene."""
        end = options.end_seconds if options.end_seconds is not None else info.duration_seconds
        if options.start_seconds >= info.duration_seconds or end > info.duration_seconds:
            raise AppError("invalid_scene", "La scène demandée dépasse la durée de la vidéo.")
        scene = SceneRange(start_seconds=options.start_seconds, end_seconds=end)
        if scene.duration_seconds > self.settings.max_scene_seconds:
            raise AppError(
                "scene_too_long",
                f"La scène doit durer au maximum {self.settings.max_scene_seconds:g} secondes. "
                "Choisissez un début et une fin.",
            )
        return scene

    def extract(self, source: Path, target: Path, info: MediaInfo, scene: SceneRange) -> float:
        """Return the actual duration of the extracted PCM16 / 16 kHz / mono WAV."""
        self._run(
            self.settings.ffmpeg_bin,
            [
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-protocol_whitelist",
                "file",
                "-format_whitelist",
                _FORMATS,
                "-ss",
                f"{scene.start_seconds:.9f}",
                "-i",
                str(source.resolve()),
                "-t",
                f"{scene.duration_seconds:.9f}",
                "-map",
                f"0:{info.audio_stream_index}",
                "-vn",
                "-sn",
                "-dn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                "-map_metadata",
                "-1",
                "-f",
                "wav",
                str(target.resolve()),
            ],
            "l'extraction audio",
        )
        try:
            with wave.open(str(target), "rb") as audio:
                if (
                    audio.getnchannels() != 1
                    or audio.getsampwidth() != 2
                    or audio.getframerate() != 16000
                    or audio.getnframes() <= 0
                ):
                    raise ValueError("invalid PCM output")
                duration = audio.getnframes() / audio.getframerate()
        except (OSError, EOFError, ValueError, wave.Error) as exc:
            raise AppError("invalid_audio", "La scène ne contient aucun audio décodable.") from exc
        return duration
