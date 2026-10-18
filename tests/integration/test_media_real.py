import subprocess
import wave

import pytest

from film_transcriber.core.config import Settings
from film_transcriber.core.errors import AppError
from film_transcriber.core.models import TranscriptionOptions
from film_transcriber.services.media import MediaService, resolve_binary

pytestmark = pytest.mark.ffmpeg


@pytest.fixture
def binaries():
    ffmpeg, ffprobe = resolve_binary("ffmpeg"), resolve_binary("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg et ffprobe absents : extraction réelle non vérifiée.")
    return ffmpeg, ffprobe


def test_synthetic_video_extraction_with_offset(tmp_path, binaries):
    ffmpeg, ffprobe = binaries
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:r=10:d=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100:duration=3",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    service = MediaService(Settings(ffmpeg_bin=ffmpeg, ffprobe_bin=ffprobe))
    info = service.inspect(source)
    assert info.audio_codec == "aac"
    assert info.video_codec == "mpeg4"
    assert info.duration_seconds == pytest.approx(3, abs=0.15)
    scene = service.select_scene(info, TranscriptionOptions(start_seconds=1, end_seconds=2.5))
    target = tmp_path / "audio.wav"
    duration = service.extract(source, target, info, scene)
    assert duration == pytest.approx(1.5, abs=0.03)
    with wave.open(str(target), "rb") as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 16000)
        assert any(audio.readframes(16000))


def test_reject_audio_disguised_as_video(tmp_path, binaries):
    ffmpeg, ffprobe = binaries
    source = tmp_path / "fake.mp4"
    with wave.open(str(source), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x00\x00" * 16000)
    with pytest.raises(AppError) as error:
        MediaService(Settings(ffmpeg_bin=ffmpeg, ffprobe_bin=ffprobe)).inspect(source)
    assert error.value.category == "invalid_media"


def test_reject_remote_playlist_disguised_as_video(tmp_path, binaries):
    ffmpeg, ffprobe = binaries
    source = tmp_path / "playlist.mp4"
    source.write_text(
        "#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nhttps://example.invalid/media.ts\n"
    )
    with pytest.raises(AppError) as error:
        MediaService(Settings(ffmpeg_bin=ffmpeg, ffprobe_bin=ffprobe)).inspect(source)
    assert error.value.category == "invalid_media"
