# Architecture et contrats du MVP

Le GO du 17 octobre 2026 autorise toutes les phases. Le cadrage établit les contrats ci-dessous. L'interface livrée affiche les résultats réellement produits par le moteur. Aucun média ni texte n'est envoyé à une API d'inférence.

## Parcours

Importer une vidéo, choisir une scène et la langue, lancer le traitement, suivre son état puis lire la vidéo à gauche et les segments à droite. La position réelle de la vidéo détermine le segment surligné et le défilement du panneau. Un clic sur un segment repositionne la vidéo. Télécharger TXT, SRT ou JSON ; supprimer explicitement un job pour effacer ses fichiers.

## Composants

| Module | Responsabilité |
| --- | --- |
| core/config.py, models.py, errors.py | Configuration FILM_*, contrats Pydantic et erreurs sûres |
| services/media.py | ffprobe, validation du média réel et de la plage, extraction WAV |
| asr/base.py, faster_whisper.py | Contrat moteur, chargement différé unique, inférence locale |
| services/transcription.py | Pipeline, mesures, création des exports |
| services/jobs.py | Upload borné, fichiers, états mémoire, exécuteur et suppression |
| api/routes.py | Transport HTTP ; délégation aux services |
| exporters/ | TXT, SRT et JSON déterministes |
| templates/, static/ | Interface accessible, polling, lecteur et texte synchronisés |

## Contrats Python

- ASREngine.transcribe(audio_path: Path, options: TranscriptionOptions) -> ASRResult ; le retour signifie que tous les segments ont été consommés.
- FasterWhisperEngine(settings: Settings) implémente ce contrat. model_path permet un dossier local ; model_cache_dir conserve les modèles téléchargés explicitement. L'inférence utilise local_files_only=True.
- MediaService(settings).inspect(path: Path) -> MediaInfo : valide conteneur, vidéo, audio, taille et durée.
- MediaService.select_scene(info: MediaInfo, options: TranscriptionOptions) -> SceneRange : borne strictement la plage et applique max_scene_seconds.
- MediaService.extract(source: Path, target: Path, info: MediaInfo, scene: SceneRange) -> float : WAV mono PCM16 16 kHz ; retourne la durée réelle du WAV.
- Exporters : render_txt(result: TranscriptionResult) -> str ; render_srt(result: TranscriptionResult) -> str ; render_json(result: TranscriptionResult) -> str.
- AppError(category, message, status_code=422) : erreur métier ; aucun contenu média ou chemin interne dans la réponse.
- TranscriptionService(settings, media, engine).process(job_id, source, filename, options, on_stage) -> TranscriptionResult ; fichiers transcript.txt/.srt/.json à côté de source, WAV temporaire supprimé dans finally.

## HTTP

| Méthode et route | Contrat |
| --- | --- |
| GET / | Page HTML |
| GET /health | Statut, disponibilité FFmpeg et configuration du modèle, sans chargement ASR |
| POST /api/jobs | multipart file, start_seconds=0, end_seconds facultatif, language=auto/fr/en, vad_filter=true, beam_size=5 ; 202 JobView |
| GET /api/jobs | Liste JobView, récents en premier |
| GET /api/jobs/{id} | JobView ; result disponible seulement après succès |
| GET /api/jobs/{id}/media | Vidéo locale, prise en charge HTTP Range |
| GET /api/jobs/{id}/exports/{format} | txt, srt ou json ; fichier après COMPLETED |
| DELETE /api/jobs/{id} | 204 ; conflit 409 si PENDING ou PROCESSING |

Erreurs : objet error contenant category et message. Les identifiants sont des UUID générés côté serveur et vérifiés avant accès au stockage. Les chemins des uploads sont déterministes par job et indépendants des noms d'origine. Les tailles sont contrôlées pendant la réception. Les validations média s'exécutent dans le worker, avec un échec explicite si le fichier est invalide.

## Temps et synchronisation

Les timestamps start/end sont relatifs à l'audio extrait. scene_start_seconds conserve l'offset de la vidéo source. Le temps scène vaut currentTime moins cet offset ; le segment est actif si start <= temps < end. Aucune sélection pendant les silences ou hors scène. La pause, le seek et le changement de vitesse utilisent les événements du lecteur. Seul le panneau de transcription défile.

## Exécution et limites

Un processus Uvicorn, un worker par défaut et un nombre total de jobs borné. Un verrou protège le chargement et l'utilisation du moteur partagé. Les états sont en mémoire et sont perdus au redémarrage ; les données sur disque ne constituent pas une base de jobs persistante. Les jobs actifs ne sont pas supprimables. Aucun pourcentage ASR inventé. Les formats non lus par le navigateur peuvent être transcrits mais la prévisualisation n'est pas garantie. Le CPU reste le mode par défaut. Le téléchargement du modèle est séparé de l'inférence.

## Vérifications attendues

Tests des plages, formats invalides, limites d'upload, génération SRT, nettoyage, transitions, erreurs des moteurs et routes. Une vidéo synthétique locale vérifie l'extraction FFmpeg sans gros modèle. Un smoke test distinct utilise un vrai modèle et une parole de synthèse locale si disponibles. Ruff, mypy et couverture >= 80 % sur les modules testables. Vérification navigateur du partage d'écran et de la synchronisation avec un offset non nul.
