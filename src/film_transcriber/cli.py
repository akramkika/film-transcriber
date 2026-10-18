"""Local command-line entry points; inference never downloads model weights."""

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from film_transcriber.asr.faster_whisper import FasterWhisperEngine, resolve_model_path
from film_transcriber.core.config import Settings
from film_transcriber.core.errors import AppError
from film_transcriber.core.models import TranscriptionOptions
from film_transcriber.services.media import MediaService, resolve_binary
from film_transcriber.services.transcription import TranscriptionService


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Le port doit être un entier.") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("Le port doit être compris entre 1 et 65535.")
    return port


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="film-transcriber",
        description="Transcription locale de scènes vidéo avec faster-whisper.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Ouvrir le serveur web local.")
    serve.add_argument("--port", type=_port, default=8000, help="Port local (défaut : 8000).")
    commands.add_parser("doctor", help="Vérifier Python, FFmpeg et le modèle local.")
    commands.add_parser("download-model", help="Télécharger explicitement le modèle configuré.")
    transcribe = commands.add_parser("transcribe", help="Transcrire une vidéo locale et exporter.")
    transcribe.add_argument("source", type=Path, help="Chemin de la vidéo.")
    transcribe.add_argument("--start", type=float, default=0, help="Début de scène en secondes.")
    transcribe.add_argument("--end", type=float, default=None, help="Fin de scène en secondes.")
    transcribe.add_argument("--language", choices=("auto", "fr", "en"), default="auto")
    transcribe.add_argument(
        "--no-vad", action="store_true", help="Désactiver la détection de voix."
    )
    transcribe.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/transcriptions"),
        help="Dossier parent des résultats ; un sous-dossier UUID est créé par traitement.",
    )
    return parser


def _check_binary(label: str, configured: str) -> bool:
    binary = resolve_binary(configured)
    if binary is None:
        print(f"[MANQUANT] {label} : installer l'exécutable ou renseigner son chemin dans .env.")
        return False
    try:
        result = subprocess.run(
            [binary, "-version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=True,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        print(f"[ERREUR] {label} : exécutable présent mais inutilisable.")
        return False
    first_line = result.stdout.splitlines()
    version = first_line[0] if first_line else "version non fournie"
    print(f"[OK] {label} : {version}")
    return True


def _doctor(settings: Settings) -> int:
    python_ok = sys.version_info[:2] == (3, 12)
    print(f"[{'OK' if python_ok else 'ERREUR'}] Python {sys.version.split()[0]} (3.12 requis)")
    ffmpeg_ok = _check_binary("FFmpeg", settings.ffmpeg_bin)
    ffprobe_ok = _check_binary("ffprobe", settings.ffprobe_bin)
    try:
        model = resolve_model_path(settings)
    except AppError:
        model_ok = False
        print("[MANQUANT] Modèle local : exécuter film-transcriber download-model.")
    else:
        model_ok = True
        print(f"[OK] Modèle local : {model}")
    print(f"Moteur configuré : {settings.model_name}, {settings.device}, {settings.compute_type}.")
    print("Le diagnostic vérifie les fichiers du modèle sans charger les poids en mémoire.")
    return 0 if all((python_ok, ffmpeg_ok, ffprobe_ok, model_ok)) else 1


def _download_model(settings: Settings) -> int:
    from faster_whisper.utils import download_model

    if settings.model_path is not None:
        raise AppError(
            "model_path_configured",
            "FILM_MODEL_PATH désigne un modèle préinstallé. Retirez ce réglage pour télécharger "
            "le modèle configuré dans FILM_MODEL_CACHE_DIR.",
        )
    settings.model_cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"Téléchargement explicite du modèle {settings.model_name} depuis Hugging Face...")
    try:
        location = download_model(settings.model_name, cache_dir=str(settings.model_cache_dir))
    except Exception as exc:
        # Network and provider errors may include local account or cache details.
        raise AppError(
            "model_download_failed",
            "Téléchargement impossible. Vérifiez le réseau, le nom du modèle et l'espace disque.",
            503,
        ) from exc
    print(f"Modèle disponible : {Path(location).resolve()}")
    return 0


def _copy_source(source: Path, target: Path, max_bytes: int) -> None:
    """Bound the copy even when the original file grows after the initial stat."""
    total = 0
    created = False
    try:
        with source.open("rb") as incoming, target.open("xb") as destination:
            created = True
            while chunk := incoming.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise AppError("file_too_large", "Le fichier dépasse la taille autorisée.", 413)
                destination.write(chunk)
        if total == 0:
            raise AppError("empty_file", "Le fichier vidéo est vide.")
    except BaseException:
        if created:
            target.unlink(missing_ok=True)
        raise


def _transcribe(args: argparse.Namespace, settings: Settings) -> int:
    options = TranscriptionOptions(
        start_seconds=args.start,
        end_seconds=args.end,
        language=None if args.language == "auto" else args.language,
        vad_filter=not args.no_vad,
        beam_size=settings.beam_size,
    )
    source = Path(args.source)
    if not source.is_file():
        raise AppError("file_missing", "Le fichier vidéo est introuvable ou inaccessible.")
    size = source.stat().st_size
    if size == 0:
        raise AppError("empty_file", "Le fichier vidéo est vide.")
    if size > settings.max_upload_bytes:
        raise AppError("file_too_large", "Le fichier dépasse la taille autorisée.", 413)
    job_id = str(uuid4())
    output_dir = (Path(args.output) / job_id).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    copied_source = output_dir / "source.media"
    _copy_source(source, copied_source, settings.max_upload_bytes)
    service = TranscriptionService(settings, MediaService(settings), FasterWhisperEngine(settings))
    result = service.process(
        job_id,
        copied_source,
        source.name,
        options,
        lambda stage: print(f"Étape : {stage}"),
    )
    print(f"Terminé : {len(result.segments)} segments, langue {result.language}.")
    print(
        f"Extraction : {result.metrics.extraction_seconds:.2f} s ; "
        f"inférence : {result.metrics.inference_seconds:.2f} s ; RTF : {result.metrics.rtf:.3f}."
    )
    print(f"Exports TXT, SRT et JSON : {output_dir}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command and report only safe diagnostics, never transcription content."""
    args = _parser().parse_args(argv)
    try:
        settings = Settings()
        match args.command:
            case "doctor":
                return _doctor(settings)
            case "download-model":
                return _download_model(settings)
            case "transcribe":
                return _transcribe(args, settings)
            case "serve":
                import uvicorn

                uvicorn.run(
                    "film_transcriber.main:create_app",
                    host="127.0.0.1",
                    port=args.port,
                    factory=True,
                )
                return 0
            case _:
                return 2
    except AppError as exc:
        print(f"Erreur [{exc.category}] : {exc.message}", file=sys.stderr)
        return 1
    except ValidationError:
        print(
            "Paramètres invalides. Vérifiez la plage de scène et la configuration .env.",
            file=sys.stderr,
        )
        return 2
    except (ImportError, OSError, RuntimeError):
        print(
            "Impossible d'exécuter la commande. Vérifiez l'installation, les permissions "
            "et l'espace disque.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("Traitement interrompu.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
