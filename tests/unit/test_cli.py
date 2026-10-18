"""CLI behavior without model downloads, network calls or real inference."""

from collections.abc import Callable
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest

from film_transcriber import cli
from film_transcriber.core.config import Settings
from film_transcriber.core.errors import AppError
from film_transcriber.core.models import ProcessingMetrics, Segment, TranscriptionResult


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    configuration = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        model_cache_dir=tmp_path / "models",
        model_path=None,
        max_upload_bytes=1024,
    )
    monkeypatch.setattr(cli, "Settings", lambda: configuration)
    return configuration


def test_serve_uses_loopback_and_selected_port(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = Mock()
    monkeypatch.setattr("uvicorn.run", run)
    assert cli.main(["serve", "--port", "8123"]) == 0
    run.assert_called_once_with(
        "film_transcriber.main:create_app", host="127.0.0.1", port=8123, factory=True
    )


@pytest.mark.parametrize("port", ["0", "65536", "invalid"])
def test_invalid_port_is_rejected(port: str) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(["serve", "--port", port])
    assert error.value.code == 2


def test_doctor_missing_model_fails_without_creating_engine(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_check_binary", lambda *args: True)
    monkeypatch.setattr(cli, "FasterWhisperEngine", Mock(side_effect=AssertionError("No load")))
    monkeypatch.setattr(
        cli,
        "resolve_model_path",
        Mock(side_effect=AppError("model_missing", "Absent")),
    )
    assert cli.main(["doctor"]) == 1
    assert "download-model" in capsys.readouterr().out


def test_download_is_explicit_and_uses_configured_cache(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    download = Mock(return_value=str(settings.model_cache_dir / "snapshot"))
    monkeypatch.setattr("faster_whisper.utils.download_model", download)
    assert cli.main(["download-model"]) == 0
    download.assert_called_once_with(settings.model_name, cache_dir=str(settings.model_cache_dir))


def test_download_refuses_custom_model_path(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings.model_path = tmp_path / "preinstalled"
    download = Mock()
    monkeypatch.setattr("faster_whisper.utils.download_model", download)
    assert cli.main(["download-model"]) == 1
    download.assert_not_called()


def test_download_error_hides_provider_details(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "faster_whisper.utils.download_model",
        Mock(side_effect=RuntimeError("private-token")),
    )
    assert cli.main(["download-model"]) == 1
    output = capsys.readouterr()
    assert "model_download_failed" in output.err
    assert "private-token" not in output.err


@pytest.mark.parametrize("parameters", [["--start", "5", "--end", "2"], ["--start", "nan"]])
def test_invalid_scene_does_not_create_output(
    settings: Settings,
    tmp_path: Path,
    parameters: list[str],
) -> None:
    output = tmp_path / "output"
    assert cli.main(["transcribe", "missing.mp4", "--output", str(output), *parameters]) == 2
    assert not output.exists()


@pytest.mark.parametrize("payload", [b"", b"x" * 1025])
def test_invalid_file_size_does_not_copy(
    settings: Settings,
    tmp_path: Path,
    payload: bytes,
) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(payload)
    output = tmp_path / "output"
    assert cli.main(["transcribe", str(source), "--output", str(output)]) == 1
    assert not output.exists()


def test_copy_limit_removes_only_its_new_partial_file(tmp_path: Path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"too large")
    with pytest.raises(AppError, match="taille"):
        cli._copy_source(source, target, max_bytes=2)
    assert not target.exists()
    assert source.read_bytes() == b"too large"


def test_copy_never_overwrites_or_removes_existing_target(tmp_path: Path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"new")
    target.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        cli._copy_source(source, target, max_bytes=1024)
    assert target.read_bytes() == b"keep"


def test_transcribe_forwards_options_uses_uuid_and_never_prints_text(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "private-name.mp4"
    source.write_bytes(b"synthetic source")
    service = Mock()

    def process(
        job_id: str,
        copied_source: Path,
        filename: str,
        options: object,
        on_stage: Callable[[str], None],
    ) -> TranscriptionResult:
        assert UUID(job_id)
        assert copied_source.name == "source.media"
        assert copied_source.parent.name == job_id
        assert copied_source.read_bytes() == source.read_bytes()
        assert filename == source.name
        on_stage("transcribing")
        return TranscriptionResult(
            job_id=job_id,
            source_filename=filename,
            source_duration_seconds=30,
            scene_start_seconds=10,
            scene_duration_seconds=5,
            segments=[Segment(start=1, end=2, text="Dialogue privé à ne pas journaliser.")],
            language="fr",
            model="small",
            device="cpu",
            compute_type="int8",
            vad_filter=False,
            beam_size=5,
            metrics=ProcessingMetrics(
                extraction_seconds=0.1,
                inference_seconds=1,
                audio_duration_seconds=5,
                rtf=0.2,
            ),
        )

    service.process.side_effect = process
    monkeypatch.setattr(cli, "TranscriptionService", Mock(return_value=service))
    assert (
        cli.main(
            [
                "transcribe",
                str(source),
                "--start",
                "10",
                "--end",
                "15",
                "--language",
                "fr",
                "--no-vad",
                "--output",
                str(tmp_path / "output"),
            ]
        )
        == 0
    )
    options = service.process.call_args.args[3]
    assert options.start_seconds == 10
    assert options.end_seconds == 15
    assert options.language == "fr"
    assert options.vad_filter is False
    output = capsys.readouterr()
    assert "Dialogue privé" not in output.out + output.err
    assert "Exports TXT, SRT et JSON" in output.out
    assert "private-name" not in output.out


def test_filesystem_failure_is_redacted(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_transcribe", Mock(side_effect=OSError("private-path")))
    assert cli.main(["transcribe", "video.mp4"]) == 1
    assert "private-path" not in capsys.readouterr().err
