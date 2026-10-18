"""Thin HTTP endpoints delegating uploads, storage and processing to services."""

from typing import Annotated, cast

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from film_transcriber.api.schemas import parse_options
from film_transcriber.core.models import JobView
from film_transcriber.services.jobs import JobManager

router = APIRouter(prefix="/api/jobs")


def manager(request: Request) -> JobManager:
    return cast(JobManager, request.app.state.jobs)


@router.post("", status_code=202, response_model=JobView)
async def create_job(
    request: Request,
    file: Annotated[UploadFile, File()],
    start_seconds: Annotated[float, Form()] = 0,
    end_seconds: Annotated[str, Form()] = "",
    language: Annotated[str, Form()] = "auto",
    vad_filter: Annotated[bool, Form()] = True,
    beam_size: Annotated[int, Form()] = 5,
) -> JobView:
    options = parse_options(start_seconds, end_seconds, language, vad_filter, beam_size)
    try:
        return await run_in_threadpool(
            manager(request).submit_upload, file.file, file.filename, options
        )
    finally:
        await file.close()


@router.get("", response_model=list[JobView])
def list_jobs(request: Request) -> list[JobView]:
    return manager(request).list_jobs()


@router.get("/{job_id}", response_model=JobView)
def get_job(request: Request, job_id: str) -> JobView:
    return manager(request).get(job_id)


@router.get("/{job_id}/media")
def get_media(request: Request, job_id: str) -> FileResponse:
    path = manager(request).media_path(job_id)
    media_type = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo",
    }[path.suffix]
    return FileResponse(path, media_type=media_type, content_disposition_type="inline")


@router.get("/{job_id}/exports/{extension}")
def export_result(request: Request, job_id: str, extension: str) -> FileResponse:
    path = manager(request).export_path(job_id, extension)
    media_type = {"txt": "text/plain", "srt": "application/x-subrip", "json": "application/json"}[
        extension
    ]
    return FileResponse(path, filename=f"transcription.{extension}", media_type=media_type)


@router.delete("/{job_id}", status_code=204)
def delete_job(request: Request, job_id: str) -> Response:
    manager(request).delete(job_id)
    return Response(status_code=204)
