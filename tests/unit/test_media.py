import json
import subprocess
import wave
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from film_transcriber.core.config import Settings
from film_transcriber.core.errors import AppError
from film_transcriber.core.models import MediaInfo, SceneRange, TranscriptionOptions
from film_transcriber.services.media import MediaService, resolve_binary


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.mp4"
    path.write_bytes(b"fixture")
    return path


@pytest.fixture
def info():
    return MediaInfo(
        duration_seconds=60,
        format_name="mov,mp4,m4a,3gp,3g2,mj2",
        audio_stream_index=1,
        audio_codec="aac",
        video_codec="h264",
        size_bytes=1234,
    )


@pytest.fixture
def probe():
    return {
        "format": {"duration": "60", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 640,
                "height": 360,
                "disposition": {"attached_pic": 0},
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 2,
                "sample_rate": "44100",
            },
        ],
    }


def service_with_probe(monkeypatch, payload):
    service = MediaService(Settings())
    monkeypatch.setattr(service, "_run", Mock(return_value=json.dumps(payload)))
    return service


def test_inspect_real_metadata_and_local_restrictions(monkeypatch, source, probe):
    service = service_with_probe(monkeypatch, probe)
    info = service.inspect(source)
    assert info.duration_seconds == 60
    assert info.audio_stream_index == 1
    assert info.size_bytes == source.stat().st_size
    arguments = service._run.call_args.args[1]
    assert arguments[arguments.index("-protocol_whitelist") + 1] == "file"
    assert arguments[arguments.index("-format_whitelist") + 1] == "mov,matroska,avi"
    assert str(source.resolve()) == arguments[-1]


def test_inspect_skips_unusable_audio(monkeypatch, source, probe):
    probe["streams"].insert(1, {"index": 2, "codec_type": "audio", "codec_name": "unknown"})
    assert service_with_probe(monkeypatch, probe).inspect(source).audio_stream_index == 1


@pytest.mark.parametrize("duration", ["NaN", "inf", "0", "-1", "garbage"])
def test_inspect_rejects_bad_duration(monkeypatch, source, probe, duration):
    probe["format"]["duration"] = duration
    with pytest.raises(AppError, match="durée"):
        service_with_probe(monkeypatch, probe).inspect(source)


@pytest.mark.parametrize("payload", [{}, [], {"format": None}, {"format": {"format_name": "hls"}}])
def test_inspect_rejects_bad_probe_structure(monkeypatch, source, payload):
    with pytest.raises(AppError) as error:
        service_with_probe(monkeypatch, payload).inspect(source)
    assert error.value.category == "invalid_media"


@pytest.mark.parametrize("kind,category", [("audio", "no_video"), ("video", "no_audio")])
def test_inspect_requires_both_streams(monkeypatch, source, probe, kind, category):
    probe["streams"] = [stream for stream in probe["streams"] if stream["codec_type"] == kind]
    with pytest.raises(AppError) as error:
        service_with_probe(monkeypatch, probe).inspect(source)
    assert error.value.category == category


def test_cover_art_is_not_video(monkeypatch, source, probe):
    probe["streams"][0]["disposition"]["attached_pic"] = 1
    with pytest.raises(AppError) as error:
        service_with_probe(monkeypatch, probe).inspect(source)
    assert error.value.category == "no_video"


def test_size_checked_before_probe(source):
    with pytest.raises(AppError) as error:
        MediaService(Settings(max_upload_bytes=1)).inspect(source)
    assert error.value.status_code == 413


def test_empty_and_missing_files(tmp_path):
    source = tmp_path / "empty.mp4"
    source.touch()
    service = MediaService(Settings())
    with pytest.raises(AppError) as error:
        service.inspect(source)
    assert error.value.category == "empty_file"
    with pytest.raises(AppError) as error:
        service.inspect(tmp_path / "absent.mp4")
    assert error.value.category == "invalid_media"


def test_scene_defaults_and_offset(info):
    service = MediaService(Settings())
    assert service.select_scene(info, TranscriptionOptions()).duration_seconds == 60
    scene = service.select_scene(info, TranscriptionOptions(start_seconds=15, end_seconds=25))
    assert (scene.start_seconds, scene.end_seconds, scene.duration_seconds) == (15, 25, 10)


@pytest.mark.parametrize(
    "options",
    [
        TranscriptionOptions(start_seconds=60),
        TranscriptionOptions(end_seconds=61),
    ],
)
def test_out_of_bounds_scene(info, options):
    with pytest.raises(AppError) as error:
        MediaService(Settings()).select_scene(info, options)
    assert error.value.category == "invalid_scene"


def test_scene_duration_limit_inclusive(info):
    service = MediaService(Settings(max_scene_seconds=10))
    service.select_scene(info, TranscriptionOptions(start_seconds=5, end_seconds=15))
    with pytest.raises(AppError) as error:
        service.select_scene(info, TranscriptionOptions(start_seconds=5, end_seconds=15.01))
    assert error.value.category == "scene_too_long"


@pytest.mark.parametrize(
    "parameters",
    [
        {"start_seconds": -1},
        {"end_seconds": 0},
        {"start_seconds": 5, "end_seconds": 3},
        {"start_seconds": float("nan")},
        {"end_seconds": float("inf")},
    ],
)
def test_invalid_scene_parameters(parameters):
    with pytest.raises(ValidationError):
        TranscriptionOptions(**parameters)


def test_subprocess_is_bounded_without_shell(monkeypatch):
    monkeypatch.setattr("film_transcriber.services.media.resolve_binary", lambda value: "ffprobe")
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, stdout="{}"))
    monkeypatch.setattr(subprocess, "run", runner)
    assert (
        MediaService(Settings(process_timeout_seconds=12))._run("ffprobe", ["-version"], "test")
        == "{}"
    )
    assert runner.call_args.kwargs["shell"] is False
    assert runner.call_args.kwargs["timeout"] == 12
    assert runner.call_args.kwargs["stdin"] == subprocess.DEVNULL


@pytest.mark.parametrize(
    "failure,category",
    [
        (subprocess.TimeoutExpired("ffprobe", 1), "media_timeout"),
        (subprocess.CalledProcessError(1, "ffprobe", stderr="PRIVATE"), "invalid_media"),
        (OSError("PRIVATE"), "ffmpeg_unavailable"),
    ],
)
def test_subprocess_errors_are_safe(monkeypatch, failure, category):
    monkeypatch.setattr("film_transcriber.services.media.resolve_binary", lambda value: "ffprobe")
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=failure))
    with pytest.raises(AppError) as error:
        MediaService(Settings())._run("ffprobe", [], "l'inspection")
    assert error.value.category == category
    assert "PRIVATE" not in error.value.message


def test_binary_missing(monkeypatch):
    monkeypatch.setattr("film_transcriber.services.media.resolve_binary", lambda value: None)
    with pytest.raises(AppError) as error:
        MediaService(Settings())._run("ffprobe", [], "test")
    assert error.value.category == "ffmpeg_missing"


def test_binary_resolution_local_and_explicit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("film_transcriber.services.media.shutil.which", lambda _: None)
    target = tmp_path / ".tools" / "ffmpeg" / "bin" / "ffprobe.exe"
    target.parent.mkdir(parents=True)
    target.touch()
    assert resolve_binary("ffprobe") == str(target)
    assert resolve_binary(str(target)) == str(target)
    assert resolve_binary("missing") is None
    assert resolve_binary(str(tmp_path / "missing" / "ffprobe.exe")) is None


def test_binary_resolution_path(monkeypatch):
    monkeypatch.setattr("film_transcriber.services.media.shutil.which", lambda _: "/usr/bin/ffmpeg")
    assert resolve_binary("ffmpeg") == "/usr/bin/ffmpeg"


def test_extract_wav_format_duration_and_mapping(tmp_path, source, info, monkeypatch):
    target = tmp_path / "audio.wav"
    recorded = []

    def run(_binary, arguments, _stage):
        recorded.extend(arguments)
        with wave.open(str(target), "wb") as audio:
            audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\x00\x00" * 16000)
        return ""

    service = MediaService(Settings())
    monkeypatch.setattr(service, "_run", run)
    duration = service.extract(source, target, info, SceneRange(start_seconds=4, end_seconds=5))
    assert duration == 1
    assert recorded[recorded.index("-map") + 1] == "0:1"
    assert recorded[recorded.index("-ss") + 1] == "4.000000000"
    assert recorded[recorded.index("-t") + 1] == "1.000000000"


def test_extract_invalid_wav(tmp_path, source, info, monkeypatch):
    service = MediaService(Settings())
    monkeypatch.setattr(service, "_run", lambda *args: "")
    with pytest.raises(AppError) as error:
        service.extract(
            source, tmp_path / "missing.wav", info, SceneRange(start_seconds=0, end_seconds=1)
        )
    assert error.value.category == "invalid_audio"
