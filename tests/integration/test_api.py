"""HTTP contracts with real orchestration and exports, simulated media and ASR."""

from collections.abc import Iterator
from pathlib import Path
from time import monotonic, sleep
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

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
from film_transcriber.main import create_app
from film_transcriber.services.media import MediaService


class FakeEngine(ASREngine):
    def transcribe(self, audio: Path, options: TranscriptionOptions) -> ASRResult:
        assert audio.is_file()
        return ASRResult(
            segments=[Segment(start=0.5, end=1.5, text="Bonjour depuis la scène.")],
            language="fr",
            language_probability=0.99,
        )


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", max_upload_bytes=32)
    app = create_app(settings, FakeEngine())
    media = Mock(spec=MediaService)
    media.inspect.return_value = MediaInfo(
        duration_seconds=30,
        format_name="mov",
        audio_stream_index=1,
        audio_codec="aac",
        video_codec="h264",
        size_bytes=5,
    )
    media.select_scene.side_effect = lambda info, options: SceneRange(
        start_seconds=options.start_seconds, end_seconds=options.end_seconds or 30
    )

    def extract(source: Path, target: Path, info: MediaInfo, scene: SceneRange) -> float:
        target.write_bytes(b"simulated audio")
        return scene.duration_seconds

    media.extract.side_effect = extract
    app.state.pipeline.media = media
    with TestClient(app) as connected:
        yield connected


def wait_terminal(client: TestClient, job_id: str) -> dict:
    deadline = monotonic() + 3
    while monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in {"COMPLETED", "FAILED"}:
            return job
        sleep(0.005)
    pytest.fail("HTTP job did not complete")


def test_full_http_cycle_preserves_scene_offset_exports_and_media_range(client: TestClient) -> None:
    response = client.post(
        "/api/jobs",
        files={"file": ("scene.mp4", b"video", "video/mp4")},
        data={"start_seconds": "10", "end_seconds": "15", "language": "fr", "vad_filter": "false"},
    )
    assert response.status_code == 202
    job_id = response.json()["id"]
    job = wait_terminal(client, job_id)
    assert job["status"] == "COMPLETED"
    assert job["result"]["scene_start_seconds"] == 10
    assert job["result"]["scene_duration_seconds"] == 5
    assert job["result"]["segments"][0]["start"] == 0.5
    assert job["result"]["vad_filter"] is False
    assert client.get("/api/jobs").json()[0]["id"] == job_id
    for extension in ("txt", "srt", "json"):
        export = client.get(f"/api/jobs/{job_id}/exports/{extension}")
        assert export.status_code == 200
        assert f"transcription.{extension}" in export.headers["content-disposition"]
        assert "Bonjour" in export.text
    srt = client.get(f"/api/jobs/{job_id}/exports/srt")
    assert "00:00:00,500 --> 00:00:01,500" in srt.text
    media = client.get(f"/api/jobs/{job_id}/media", headers={"Range": "bytes=1-3"})
    assert media.status_code == 206
    assert media.content == b"ide"
    assert media.headers["content-range"] == "bytes 1-3/5"
    assert client.get(f"/api/jobs/{job_id}/exports/exe").status_code == 404
    assert client.delete(f"/api/jobs/{job_id}").status_code == 204
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    assert client.get(f"/api/jobs/{job_id}/media").status_code == 404
    assert client.get("/api/jobs").json() == []


@pytest.mark.parametrize(
    "filename,payload,status,category",
    [
        ("video.mp4", b"", 422, "empty_file"),
        ("video.mp4", b"x" * 33, 413, "file_too_large"),
        ("video.exe", b"x", 422, "unsupported_extension"),
    ],
)
def test_rejected_uploads_have_safe_errors_and_no_jobs(client, filename, payload, status, category):
    response = client.post("/api/jobs", files={"file": (filename, payload, "video/mp4")})
    assert response.status_code == status
    assert response.json()["error"]["category"] == category
    assert client.get("/api/jobs").json() == []


@pytest.mark.parametrize(
    "data",
    [
        {"language": "invalid"},
        {"start_seconds": "10", "end_seconds": "2"},
        {"end_seconds": "NaN"},
        {"beam_size": "0"},
        {"start_seconds": "not-a-number"},
    ],
)
def test_bad_options_are_rejected_before_job_creation(client: TestClient, data: dict) -> None:
    response = client.post("/api/jobs", files={"file": ("video.mp4", b"video")}, data=data)
    assert response.status_code == 422
    assert "error" in response.json()
    assert client.get("/api/jobs").json() == []


def test_missing_file_uses_consistent_error_envelope(client: TestClient) -> None:
    response = client.post("/api/jobs", data={"language": "fr"})
    assert response.status_code == 422
    assert response.json()["error"]["category"] == "invalid_request"


def test_invalid_real_media_fails_in_worker_without_exposing_source(client: TestClient) -> None:
    client.app.state.pipeline.media.inspect.side_effect = AppError("no_audio", "Aucune piste audio")
    response = client.post("/api/jobs", files={"file": ("video.mp4", b"invalid")})
    assert response.status_code == 202
    job_id = response.json()["id"]
    job = wait_terminal(client, job_id)
    assert job["status"] == "FAILED"
    assert job["result"] is None
    assert job["error"]["category"] == "no_audio"
    assert client.get(f"/api/jobs/{job_id}/media").status_code == 409
    assert client.get(f"/api/jobs/{job_id}/exports/txt").status_code == 409
    assert client.delete(f"/api/jobs/{job_id}").status_code == 204


@pytest.mark.parametrize("job_id", ["not-an-id", "..%5Csecret", "%2E%2E%2Fsecret"])
def test_unknown_identifiers_do_not_access_files(client: TestClient, job_id: str) -> None:
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    assert client.delete(f"/api/jobs/{job_id}").status_code == 404


def test_host_and_origin_restrictions(client: TestClient) -> None:
    assert client.get("/health", headers={"host": "remote.example"}).status_code == 400
    response = client.post(
        "/api/jobs",
        files={"file": ("video.mp4", b"video")},
        headers={"origin": "https://remote.example"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["category"] == "invalid_origin"
    assert client.get("/health", headers={"host": "localhost"}).status_code == 200


@pytest.mark.parametrize("length", ["-1", "garbage", "1048610"])
def test_oversized_or_invalid_content_length_is_rejected(client: TestClient, length: str) -> None:
    response = client.post("/api/jobs", content=b"x", headers={"content-length": length})
    assert response.status_code == 413


def test_index_health_and_static_assets_load(client: TestClient) -> None:
    index = client.get("/")
    assert index.status_code == 200
    assert "<video" in index.text
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/static/sync.mjs").status_code == 200
