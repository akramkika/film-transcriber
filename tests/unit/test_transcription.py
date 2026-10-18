"""Pipeline behavior with deterministic media and ASR boundary doubles."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from film_transcriber.asr.base import ASREngine
from film_transcriber.core.config import Settings
from film_transcriber.core.errors import AppError
from film_transcriber.core.models import (
    ASRResult,
    MediaInfo,
    SceneRange,
    Segment,
    TranscriptionOptions,
)
from film_transcriber.services.media import MediaService
from film_transcriber.services.transcription import TranscriptionService


@pytest.fixture
def pipeline(tmp_path: Path) -> tuple[TranscriptionService, Mock, Mock, Path]:
    settings = Settings(_env_file=None, data_dir=tmp_path)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original video")
    media = Mock(spec=MediaService)
    media.inspect.return_value = MediaInfo(
        duration_seconds=30,
        format_name="mov",
        audio_stream_index=1,
        audio_codec="aac",
        video_codec="h264",
        size_bytes=source.stat().st_size,
    )
    media.select_scene.return_value = SceneRange(start_seconds=10, end_seconds=15)

    def extract(source: Path, target: Path, info: MediaInfo, scene: SceneRange) -> float:
        target.write_bytes(b"temporary audio")
        return 5

    media.extract.side_effect = extract
    engine = Mock(spec=ASREngine)
    engine.transcribe.return_value = ASRResult(
        segments=[Segment(start=0.5, end=1.5, text="Une phrase.")],
        language="fr",
        language_probability=0.99,
    )
    return TranscriptionService(settings, media, engine), media, engine, source


def test_process_publishes_exports_scene_offset_and_measured_rtf(
    pipeline: tuple[TranscriptionService, Mock, Mock, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, media, engine, source = pipeline
    monkeypatch.setattr(
        "film_transcriber.services.transcription.perf_counter", Mock(side_effect=[0, 2, 5, 8])
    )
    stages: list[str] = []
    options = TranscriptionOptions(
        start_seconds=10, end_seconds=15, language="fr", vad_filter=False
    )
    result = service.process("test-job", source, "original.mp4", options, stages.append)
    assert stages == ["validating", "extracting", "transcribing", "exporting"]
    assert result.scene_start_seconds == 10
    assert result.scene_duration_seconds == 5
    assert result.source_duration_seconds == 30
    assert result.metrics.extraction_seconds == 2
    assert result.metrics.inference_seconds == 3
    assert result.metrics.rtf == 0.6
    assert result.vad_filter is False
    media.inspect.assert_called_once_with(source)
    engine.transcribe.assert_called_once_with(source.with_name("audio.wav"), options)
    assert source.with_name("transcript.txt").read_text(encoding="utf-8") == "Une phrase.\n"
    assert "00:00:00,500 --> 00:00:01,500" in source.with_name("transcript.srt").read_text()
    exported = json.loads(source.with_name("transcript.json").read_text(encoding="utf-8"))
    assert exported["scene_start_seconds"] == 10
    assert exported["segments"][0]["start"] == 0.5
    assert source.read_bytes() == b"original video"
    assert not source.with_name("audio.wav").exists()
    assert not list(source.parent.glob("*.tmp"))


def test_silent_scene_still_has_valid_empty_exports(
    pipeline: tuple[TranscriptionService, Mock, Mock, Path],
) -> None:
    service, _, engine, source = pipeline
    engine.transcribe.return_value = ASRResult(segments=[], language="fr")
    result = service.process(
        "silence", source, "silence.mp4", TranscriptionOptions(), lambda _: None
    )
    assert result.segments == []
    assert source.with_name("transcript.srt").read_text() == ""
    assert json.loads(source.with_name("transcript.json").read_text())["segments"] == []


@pytest.mark.parametrize("failure", [AppError("asr_failed", "Échec sûr"), MemoryError("secret")])
def test_failed_inference_cleans_audio_and_does_not_publish_exports(
    pipeline: tuple[TranscriptionService, Mock, Mock, Path],
    failure: Exception,
) -> None:
    service, _, engine, source = pipeline
    engine.transcribe.side_effect = failure
    with pytest.raises(type(failure)):
        service.process("failure", source, "video.mp4", TranscriptionOptions(), lambda _: None)
    assert not source.with_name("audio.wav").exists()
    assert not list(source.parent.glob("transcript.*"))
    assert source.exists()


def test_failed_extraction_cleans_partially_written_audio(
    pipeline: tuple[TranscriptionService, Mock, Mock, Path],
) -> None:
    service, media, engine, source = pipeline

    def fail_extract(*args: object) -> None:
        source.with_name("audio.wav").write_bytes(b"partial")
        raise AppError("media_timeout", "Délai dépassé")

    media.extract.side_effect = fail_extract
    with pytest.raises(AppError, match="Délai"):
        service.process("failure", source, "video.mp4", TranscriptionOptions(), lambda _: None)
    engine.transcribe.assert_not_called()
    assert not source.with_name("audio.wav").exists()


def test_segments_beyond_audio_duration_are_rejected(
    pipeline: tuple[TranscriptionService, Mock, Mock, Path],
) -> None:
    service, _, engine, source = pipeline
    engine.transcribe.return_value = ASRResult(
        segments=[Segment(start=4, end=8, text="Débordement")], language="fr"
    )
    with pytest.raises(AppError) as error:
        service.process("invalid", source, "video.mp4", TranscriptionOptions(), lambda _: None)
    assert error.value.category == "invalid_segments"
    assert not source.with_name("audio.wav").exists()
    assert not source.with_name("transcript.json").exists()


def test_export_failure_cleans_temporary_files(
    pipeline: tuple[TranscriptionService, Mock, Mock, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, _, source = pipeline
    original = Path.replace

    def fail_publication(path: Path, target: Path) -> Path:
        if path.name == "transcript.srt.tmp":
            raise OSError("disk unavailable")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", fail_publication)
    with pytest.raises(OSError):
        service.process(
            "failed-export", source, "video.mp4", TranscriptionOptions(), lambda _: None
        )
    assert not source.with_name("audio.wav").exists()
    assert not list(source.parent.glob("*.tmp"))
