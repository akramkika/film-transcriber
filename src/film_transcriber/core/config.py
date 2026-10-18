"""Environment configuration; safe defaults for a single local user."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings may be supplied via FILM_* environment variables or .env."""

    model_config = SettingsConfigDict(env_prefix="FILM_", env_file=".env", extra="ignore")
    data_dir: Path = Path(".data")
    model_cache_dir: Path = Path(".models")
    model_name: str = "small"
    model_path: Path | None = None
    device: str = "cpu"
    compute_type: str = "int8"
    cpu_threads: int = Field(default=4, ge=1, le=64)
    max_upload_bytes: int = Field(default=500_000_000, ge=1)
    max_scene_seconds: float = Field(default=600, gt=0, allow_inf_nan=False)
    max_jobs: int = Field(default=20, ge=1, le=1000)
    max_workers: int = Field(default=1, ge=1, le=4)
    process_timeout_seconds: float = Field(default=180, gt=0, allow_inf_nan=False)
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    beam_size: int = Field(default=5, ge=1, le=10)
