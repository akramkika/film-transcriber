# Film Transcriber

Application locale pour transcrire une scène vidéo et suivre les dialogues pendant la lecture. La vue partagée réserve un panneau à la vidéo et un panneau au texte : le segment lu est surligné et le texte défile avec la vidéo. Un clic sur un dialogue repositionne la lecture.

Le [rapport de validation](docs/validation.md) détaille les résultats exécutés, le test de transcription réelle et les limites de cette livraison.

Python 3.12, FastAPI, faster-whisper et FFmpeg. Le modèle par défaut est `small` multilingue, sur CPU en INT8. L'inférence fonctionne avec des poids présents localement ; le téléchargement du modèle est une commande explicite.

## Démarrage

Exécuter les commandes depuis le dossier du projet. Installer [uv](https://docs.astral.sh/uv/getting-started/installation/) et [FFmpeg avec ffprobe](https://ffmpeg.org/download.html), puis rendre les deux exécutables accessibles dans le `PATH`.

Sous Windows, une installation portable de FFmpeg peut aussi être placée dans `.tools/ffmpeg/bin/` avec `ffmpeg.exe` et `ffprobe.exe`. Les chemins explicites peuvent être renseignés dans `.env` ; voir [.env.example](.env.example).

Sous Debian/Ubuntu, FFmpeg est disponible via `sudo apt install ffmpeg`. Sous macOS avec Homebrew : `brew install ffmpeg`.

```shell
uv python install 3.12
uv sync --locked
uv run python -m film_transcriber.cli doctor
```

Le premier diagnostic signale normalement que le modèle manque. Télécharger ensuite le modèle, une seule fois ; cette commande accède à Hugging Face :

```shell
uv run python -m film_transcriber.cli download-model
uv run python -m film_transcriber.cli doctor
uv run python -m film_transcriber.cli serve
```

Ouvrir [http://127.0.0.1:8000](http://127.0.0.1:8000). Un autre port est possible avec `uv run film-transcriber serve --port 8001`.

Sous Windows, si le contrôle d'applications bloque le lanceur `film-transcriber.exe`, utiliser la forme `uv run python -m film_transcriber.cli` montrée ci-dessus pour toutes les commandes. Aucun réglage de sécurité Windows n'est modifié.

PyAV est limité aux versions antérieures à 19 : faster-whisper 1.2 utilise le paramètre `metadata_errors`, supprimé de PyAV 19. Le verrou de dépendances conserve la version vérifiée.

L'installation des dépendances et le téléchargement initial nécessitent Internet. Les traitements suivants ne téléchargent pas de modèle. Le dossier `.models/` doit rester disponible ; on peut fournir un modèle CTranslate2 existant avec `FILM_MODEL_PATH`.

## Utilisation

1. Sélectionner une vidéo MP4, MKV, MOV ou AVI, jusqu'à 500 Mo par défaut.
2. Choisir éventuellement un début et une fin en secondes. La scène traitée peut durer jusqu'à 10 minutes. Pour une vidéo plus longue, sélectionner une plage.
3. Choisir la détection automatique de langue, le français ou l'anglais. La détection de voix (VAD) est activée par défaut.
4. Lancer la transcription et attendre l'état terminé. Le suivi affiche l'étape courante ; la durée dépend du processeur et de la scène.
5. Lire la vidéo : le dialogue correspondant reste visible dans le panneau de texte. Utiliser les dialogues pour naviguer dans la scène.
6. Télécharger les exports TXT, SRT et JSON.

Les horodatages exportés commencent à zéro au début de la scène sélectionnée. Le JSON conserve `scene_start_seconds` : le lecteur l'ajoute aux horodatages des segments pour retrouver leur position dans la vidéo complète. La synchronisation est au niveau des segments, pas mot par mot. Le texte est disponible après la transcription, sans transcription en direct pendant la lecture.

La capacité à transcrire un fichier dépend de FFmpeg ; sa lecture dans la page dépend aussi des codecs du navigateur. Un MP4 avec vidéo H.264 et audio AAC est un choix courant pour tester la vue synchronisée. Un fichier MKV ou AVI peut être transcrit même si son aperçu ne fonctionne pas. Le MVP ne convertit pas automatiquement la vidéo pour le navigateur.

## Ligne de commande

La CLI utilise les mêmes validations, extraction, moteur et exports que l'application web. Elle crée un sous-dossier UUID distinct dans le dossier de sortie pour chaque traitement et conserve une copie du média.

```shell
uv run film-transcriber transcribe "ma-video.mp4" --language fr
uv run film-transcriber transcribe "ma-video.mp4" --start 30 --end 75 --output artifacts/transcriptions
uv run film-transcriber transcribe "ma-video.mp4" --no-vad
uv run film-transcriber --help
```

Les messages de progression n'affichent pas les dialogues. Les résultats sont écrits sur disque en UTF-8. La CLI indique le dossier des exports une fois le traitement terminé.

## Configuration

Copier `.env.example` vers `.env` pour modifier les réglages. `.env` est lu depuis le dossier de travail ; lancer les commandes depuis la racine du projet. Les variables d'environnement `FILM_*` ont priorité.

| Variable | Valeur initiale | Rôle |
| --- | --- | --- |
| `FILM_DATA_DIR` | `.data` | Médias et résultats des tâches web |
| `FILM_MODEL_CACHE_DIR` | `.models` | Cache des modèles téléchargés explicitement |
| `FILM_MODEL_NAME` | `small` | Modèle utilisé par défaut |
| `FILM_MODEL_PATH` | non définie | Dossier d'un modèle CTranslate2 déjà installé |
| `FILM_DEVICE` | `cpu` | Matériel d'inférence |
| `FILM_COMPUTE_TYPE` | `int8` | Quantification CPU |
| `FILM_CPU_THREADS` | `4` | Threads CPU du moteur |
| `FILM_MAX_UPLOAD_BYTES` | `500000000` | Limite par vidéo, en octets |
| `FILM_MAX_SCENE_SECONDS` | `600` | Durée maximale d'une scène |
| `FILM_MAX_JOBS` | `20` | Nombre maximal de tâches conservées en mémoire |
| `FILM_MAX_WORKERS` | `1` | Nombre maximal de traitements simultanés |
| `FILM_PROCESS_TIMEOUT_SECONDS` | `180` | Délai maximal par commande média externe |
| `FILM_FFMPEG_BIN` / `FILM_FFPROBE_BIN` | `ffmpeg` / `ffprobe` | Exécutables ou chemins explicites |
| `FILM_BEAM_SIZE` | `5` | Paramètre de recherche du moteur |

Le support GPU dépend d'une installation CUDA/CTranslate2 compatible et n'est pas requis pour ce MVP. La configuration CPU est la référence pour le premier essai.

## Vérification

```shell
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov=film_transcriber --cov-report=term-missing
node --test tests/frontend/*.test.mjs
```

La suite automatique utilise un moteur simulé pour vérifier les contrats, les erreurs, les exports et les échanges HTTP. Les tests média marqués `ffmpeg` utilisent les exécutables locaux ; sans eux, ces cas sont ignorés. Aucun test automatique standard ne télécharge les poids Whisper. Les tests de synchronisation JavaScript utilisent le lanceur intégré à Node.js (version 22 recommandée).

Le protocole de [test manuel et ASR réel](docs/smoke-test.md) décrit les vérifications distinctes à réaliser avec une courte vidéo parlée et un modèle local. Une suite de tests avec moteur simulé ne démontre pas la qualité de reconnaissance sur une vidéo réelle.

La configuration [pre-commit](.pre-commit-config.yaml) utilise l'environnement verrouillé du projet. Son installation dans Git reste une opération à effectuer par l'utilisateur. Le workflow [CI](.github/workflows/ci.yml) exécute les contrôles sur Python 3.12 et installe FFmpeg. Sa présence ne signifie pas qu'une exécution distante a eu lieu.

## Stockage et limites du MVP

- Le serveur écoute sur `127.0.0.1` et vise un seul utilisateur local. Aucune authentification ou exposition publique n'est prévue.
- Les états de tâches sont en mémoire. Après un redémarrage, les médias et exports restent sur disque mais les anciennes tâches ne sont plus récupérables par l'API. Sauvegarder les exports souhaités avant de nettoyer les dossiers.
- Les vidéos et les résultats occupent l'espace disque local ; l'audio temporaire est supprimé après le traitement. Une tâche terminée peut être supprimée explicitement depuis l'API. Le MVP ne comporte pas de purge automatique des données anciennes.
- Les noms de stockage et identifiants internes sont générés par l'application. Les journaux ne contiennent ni les transcriptions ni les contenus médias.
- Il n'y a ni séparation des locuteurs, ni édition des transcriptions, ni traduction. Musique, bruit et voix superposées peuvent réduire la qualité.
- Une tâche en cours n'a pas de bouton d'annulation. L'inférence n'affiche pas d'estimation de durée garantie.

L'organisation des composants, les routes et les contrats sont détaillés dans [docs/architecture.md](docs/architecture.md).

## Dépannage

| Symptôme | Action |
| --- | --- |
| Modèle absent | Exécuter explicitement `uv run film-transcriber download-model`, puis `doctor` |
| FFmpeg ou ffprobe absent | Installer les deux exécutables ou régler leurs chemins dans `.env` |
| Lecture vidéo indisponible | Essayer un MP4 H.264/AAC ; le traitement ASR peut fonctionner sans aperçu |
| Scène trop longue | Préciser un début et une fin dont l'écart respecte la limite |
| Vidéo sans audio ou invalide | Choisir une vidéo contenant une piste audio lisible |
| Mémoire insuffisante | Fermer d'autres applications ou sélectionner explicitement un modèle plus petit et le télécharger |
| Traitement lent | Réduire la durée de la scène et conserver un seul traitement simultané |
| Port occupé | Démarrer avec `serve --port 8001` |
