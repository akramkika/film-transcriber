"""FastAPI application factory with one shared, lazy-loaded ASR engine."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from film_transcriber.api.middleware import LocalUploadGuard
from film_transcriber.api.routes import router
from film_transcriber.asr.base import ASREngine
from film_transcriber.asr.faster_whisper import FasterWhisperEngine
from film_transcriber.core.config import Settings
from film_transcriber.core.errors import AppError
from film_transcriber.core.logging import configure_logging
from film_transcriber.services.jobs import JobManager
from film_transcriber.services.media import MediaService, resolve_binary
from film_transcriber.services.transcription import TranscriptionService


def create_app(settings: Settings | None = None, engine: ASREngine | None = None) -> FastAPI:
    """Build an isolated app; tests may inject an ASR engine and a temporary data root."""
    settings = settings or Settings()
    configure_logging()
    pipeline = TranscriptionService(
        settings, MediaService(settings), engine or FasterWhisperEngine(settings)
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        jobs = JobManager(settings, pipeline)
        app.state.jobs = jobs
        yield
        await run_in_threadpool(jobs.shutdown)

    app = FastAPI(title="Scène — transcription locale", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.pipeline = pipeline
    app.add_middleware(LocalUploadGuard, max_bytes=settings.max_upload_bytes)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"]
    )
    package = Path(__file__).parent
    app.mount("/static", StaticFiles(directory=package / "static"), name="static")
    templates = Jinja2Templates(directory=package / "templates")
    app.include_router(router)

    @app.exception_handler(AppError)
    async def domain_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            {"error": {"category": exc.category, "message": exc.message}}, exc.status_code
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "category": "invalid_request",
                    "message": "Vérifiez le fichier et les paramètres transmis.",
                }
            },
            422,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        category = "file_too_large" if exc.status_code == 413 else "http_error"
        return JSONResponse(
            {"error": {"category": category, "message": str(exc.detail)}}, exc.status_code
        )

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "max_upload_bytes": settings.max_upload_bytes,
                "max_scene_seconds": settings.max_scene_seconds,
            },
        )

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "ffmpeg": resolve_binary(settings.ffmpeg_bin) is not None,
            "ffprobe": resolve_binary(settings.ffprobe_bin) is not None,
            "model": settings.model_name,
            "device": settings.device,
            "compute_type": settings.compute_type,
        }

    return app
