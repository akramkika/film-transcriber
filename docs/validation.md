# Livraison du MVP — 18 octobre 2026

## Résultat observé

Le parcours complet a été exécuté dans Microsoft Edge : import d'une vidéo parlée générée localement, sélection d'un début à 2 secondes, extraction FFmpeg, vraie inférence faster-whisper small sur CPU INT8, consultation des segments et téléchargement TXT/SRT/JSON. Aucun résultat ASR simulé n'est affiché dans l'application.

| Vérification | Résultat |
| --- | --- |
| Tests Python | 122 réussis, aucun ignoré : 100 unitaires et 22 d'intégration |
| Tests JavaScript de synchronisation | 6 réussis |
| Couverture mesurée | 98,35 % ; CLI et assemblage main exclus du calcul, mais testés par les tests CLI/API |
| Ruff check et format | Réussis |
| mypy | Réussi sur 23 fichiers source |
| Diagnostic local | Python 3.12.14, FFmpeg/ffprobe 9.0.2, modèle small présent |
| Test ASR réel | 5 segments en français ; audio extrait 31,756 s ; extraction 1,300 s ; inférence 71,397 s ; RTF 2,248 |
| Test navigateur | Offset de scène, clic sur timestamps, absence de sélection avant scène, lecture x2, pause, exports, panneaux côte à côte et affichage mobile vérifiés |
| Erreurs JavaScript | Aucune observée pendant le test navigateur |

La vidéo de test contient une voix synthétisée par Windows sur un fond uni ; elle sert à valider le fonctionnement du pipeline et ne représente pas la qualité obtenue sur un film avec musique ou voix superposées. Le premier chargement du modèle est inclus dans la durée d'inférence mesurée.

## Fichiers et organisation

- `src/film_transcriber/core/` : configuration et contrats Pydantic.
- `services/` : validation média, pipeline et file de tâches bornée.
- `asr/` : interface abstraite et moteur faster-whisper local.
- `api/` : routes, contrôle des uploads et erreurs HTTP.
- `exporters/` : TXT, SRT, JSON.
- `templates/` et `static/` : interface française, vidéo et transcription avec défilement indépendant.
- `tests/`, `pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml` : vérifications et reproductibilité.

Les détails et contrats sont décrits dans `architecture.md`. Aucune commande Git n'a été exécutée.

## Reproduire

Depuis la racine du projet :

```powershell
uv sync --locked
uv run python -m film_transcriber.cli doctor
uv run python -m film_transcriber.cli serve --port 8001
```

Ouvrir <http://127.0.0.1:8001>. Le modèle et FFmpeg sont déjà présents dans ce poste, respectivement sous `.models/` et `.tools/ffmpeg/bin/`. Pour une nouvelle machine, suivre l'installation FFmpeg et la commande explicite `download-model` du README.

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov=film_transcriber --cov-report=term-missing
node --test tests/frontend/sync.test.mjs
```

Dans le sandbox Codex de ce poste, les sockets internes de TestClient sont bloquées : les tests d'intégration ont donc été exécutés avec l'autorisation de sortir du sandbox. Ils ne nécessitent aucun réseau externe. Les répertoires temporaires de ces vérifications sont sous `artifacts/`.

La génération Windows du média de test est disponible dans `scripts/create-smoke-video.ps1`. `scripts/browser-smoke.cjs` est une vérification manuelle facultative nécessitant Playwright et Microsoft Edge ; ces outils ne sont pas nécessaires au fonctionnement de l'application. Les captures observées sont `artifacts/ui-desktop.png` et `artifacts/ui-mobile.png`, avec les mesures dans `artifacts/smoke-result.json`.

## Corrections réalisées et limites

- La combinaison faster-whisper 1.2.1 / PyAV 19.0.1 échouait lors du décodage audio. PyAV 18.1.0 est désormais verrouillé et un test réel du décodeur protège cette frontière entre bibliothèques.
- Le lanceur Windows `film-transcriber.exe` a été bloqué par le contrôle d'applications de ce poste ; les commandes documentées utilisent le module Python sans modifier les réglages de sécurité.
- Les états des jobs sont en mémoire : après redémarrage, leurs fichiers restent sur disque mais l'historique n'est plus affiché. Exporter les résultats à conserver.
- Pas d'annulation d'un job actif, d'édition du texte, de diarisation ni de traduction. Le suivi est au niveau des segments, pas des mots.
- La prévisualisation dépend des codecs du navigateur ; MP4 H.264/AAC est le format testé. Les formats MP4/MKV/MOV/AVI sont inspectés par FFmpeg.
- L'inférence force la résolution locale des modèles. Le test avec réseau physiquement coupé et l'évaluation sur de vraies scènes de films restent non vérifiés.
- Le workflow CI est configuré ; son exécution sur GitHub reste non vérifiée.

## Trois améliorations pour la prochaine session

1. Persister l'historique et ajouter un nettoyage configurable des anciens fichiers.
2. Ajouter une correction manuelle des dialogues et la régénération des exports.
3. Mesurer qualité et vitesse sur plusieurs scènes de films réelles, puis ajuster le modèle et les réglages au matériel.
