"""Queue, persistence boundaries, upload limits and safe terminal states."""

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from film_transcriber.core.config import Settings
from film_transcriber.core.errors import AppError
from film_transcriber.core.models import (
    JobStatus,
    JobView,
    ProcessingMetrics,
    Segment,
    TranscriptionOptions,
    TranscriptionResult,
)
from film_transcriber.services.jobs import JobManager
from film_transcriber.services.transcription import TranscriptionService


def wait_terminal(manager: JobManager, job_id: str) -> JobView:
    deadline = monotonic() + 3
    while monotonic() < deadline:
        view = manager.get(job_id)
        if view.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
            return view
        sleep(0.005)
    pytest.fail("Worker did not reach a terminal state")


@pytest.fixture
def manager(tmp_path: Path) -> Iterator[tuple[JobManager, Mock]]:
    pipeline = Mock(spec=TranscriptionService)

    def process(job_id, source, filename, options, on_stage):
        on_stage("transcribing")
        source.with_name("transcript.txt").write_text("Dialogue", encoding="utf-8")
        return TranscriptionResult(
            job_id=job_id,
            source_filename=filename,
            source_duration_seconds=5,
            scene_start_seconds=0,
            scene_duration_seconds=5,
            segments=[Segment(start=0, end=1, text="Dialogue")],
            language="fr",
            model="small",
            device="cpu",
            compute_type="int8",
            vad_filter=True,
            beam_size=5,
            metrics=ProcessingMetrics(
                extraction_seconds=0.1, inference_seconds=0.5, audio_duration_seconds=5, rtf=0.1
            ),
        )

    pipeline.process.side_effect = process
    queue = JobManager(
        Settings(_env_file=None, data_dir=tmp_path / "data", max_upload_bytes=16, max_jobs=2),
        pipeline,
    )
    try:
        yield queue, pipeline
    finally:
        queue.shutdown()


def test_success_normalizes_name_uses_uuid_and_returns_defensive_copies(manager) -> None:
    queue, _ = manager
    pending = queue.submit_upload(
        BytesIO(b"movie"), "C:\\private\\film.mp4", TranscriptionOptions()
    )
    assert pending.status == JobStatus.PENDING
    assert str(UUID(pending.id)) == pending.id
    assert pending.original_filename == "film.mp4"
    complete = wait_terminal(queue, pending.id)
    assert complete.status == JobStatus.COMPLETED
    assert complete.stage == "completed"
    assert complete.updated_at >= complete.created_at
    complete.result.segments[0].text = "modified caller copy"
    assert queue.get(pending.id).result.segments[0].text == "Dialogue"
    path = queue.media_path(pending.id)
    assert path == queue.root / pending.id / "source.mp4"
    assert path.read_bytes() == b"movie"
    assert queue.export_path(pending.id, "txt").read_text() == "Dialogue"
    queue.delete(pending.id)
    assert not path.parent.exists()
    assert queue.list_jobs() == []


@pytest.mark.parametrize(
    "payload,filename,category",
    [
        (b"", "video.mp4", "empty_file"),
        (b"x" * 17, "video.mp4", "file_too_large"),
        (b"x", "video.txt", "unsupported_extension"),
        (b"x", None, "unsupported_extension"),
    ],
)
def test_rejected_uploads_leave_no_files_or_queue_reservations(
    manager, payload, filename, category
):
    queue, _ = manager
    with pytest.raises(AppError) as error:
        queue.submit_upload(BytesIO(payload), filename, TranscriptionOptions())
    assert error.value.category == category
    assert not list(queue.root.iterdir())
    assert queue.list_jobs() == []
    accepted = queue.submit_upload(BytesIO(b"ok"), "video.mp4", TranscriptionOptions())
    assert wait_terminal(queue, accepted.id).status == JobStatus.COMPLETED


def test_queue_limit_counts_finished_jobs_until_deleted(manager) -> None:
    queue, _ = manager
    first = queue.submit_upload(BytesIO(b"1"), "one.mp4", TranscriptionOptions())
    second = queue.submit_upload(BytesIO(b"2"), "two.mp4", TranscriptionOptions())
    wait_terminal(queue, first.id)
    wait_terminal(queue, second.id)
    assert [view.id for view in queue.list_jobs()] == [second.id, first.id]
    with pytest.raises(AppError) as error:
        queue.submit_upload(BytesIO(b"3"), "three.mp4", TranscriptionOptions())
    assert error.value.status_code == 429
    queue.delete(first.id)
    third = queue.submit_upload(BytesIO(b"3"), "three.mp4", TranscriptionOptions())
    assert wait_terminal(queue, third.id).status == JobStatus.COMPLETED


def test_active_jobs_cannot_be_deleted_or_read_and_queue_waits(manager) -> None:
    queue, pipeline = manager
    started, release = Event(), Event()
    original = pipeline.process.side_effect

    def block(*args):
        started.set()
        if not release.wait(3):
            raise RuntimeError("test did not release worker")
        return original(*args)

    pipeline.process.side_effect = block
    first = queue.submit_upload(BytesIO(b"1"), "one.mp4", TranscriptionOptions())
    try:
        assert started.wait(2)
        assert queue.get(first.id).status == JobStatus.PROCESSING
        second = queue.submit_upload(BytesIO(b"2"), "two.mp4", TranscriptionOptions())
        assert queue.get(second.id).status == JobStatus.PENDING
        for operation in (
            lambda: queue.delete(first.id),
            lambda: queue.media_path(first.id),
            lambda: queue.export_path(first.id, "txt"),
            lambda: queue.delete(second.id),
        ):
            with pytest.raises(AppError) as error:
                operation()
            assert error.value.status_code == 409
    finally:
        release.set()
    assert wait_terminal(queue, first.id).status == JobStatus.COMPLETED
    assert wait_terminal(queue, second.id).status == JobStatus.COMPLETED


@pytest.mark.parametrize(
    "failure,category",
    [
        (AppError("no_audio", "Aucune piste audio"), "no_audio"),
        (MemoryError("private payload"), "out_of_memory"),
        (RuntimeError("private payload"), "processing_failed"),
    ],
)
def test_failed_workers_return_safe_errors_and_can_be_deleted(manager, failure, category) -> None:
    queue, pipeline = manager
    pipeline.process.side_effect = failure
    job = queue.submit_upload(BytesIO(b"movie"), "video.mp4", TranscriptionOptions())
    failed = wait_terminal(queue, job.id)
    assert failed.status == JobStatus.FAILED
    assert failed.error.category == category
    assert "private payload" not in failed.model_dump_json()
    queue.delete(job.id)
    assert queue.list_jobs() == []


@pytest.mark.parametrize("job_id", ["../outside", "not-an-id", str(uuid4()), str(uuid4()).upper()])
def test_unknown_and_noncanonical_ids_are_never_paths(manager, job_id) -> None:
    queue, _ = manager
    for operation in (queue.get, queue.delete, queue.media_path):
        with pytest.raises(AppError) as error:
            operation(job_id)
        assert error.value.status_code == 404


def test_unknown_export_and_shutdown_reject_new_work(manager) -> None:
    queue, _ = manager
    with pytest.raises(AppError) as error:
        queue.export_path(str(uuid4()), "../../outside")
    assert error.value.category == "unknown_export"
    queue.shutdown()
    with pytest.raises(AppError) as error:
        queue.submit_upload(BytesIO(b"movie"), "video.mp4", TranscriptionOptions())
    assert error.value.category == "shutting_down"
    assert not list(queue.root.iterdir())


def test_failing_upload_stream_cleans_partial_directory(manager) -> None:
    queue, _ = manager
    stream = Mock()
    stream.read.side_effect = [b"first bytes", OSError("read failed")]
    with pytest.raises(OSError):
        queue.submit_upload(stream, "video.mp4", TranscriptionOptions())
    assert not list(queue.root.iterdir())
    assert queue.list_jobs() == []
