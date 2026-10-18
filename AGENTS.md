# Conventions du projet

- Appliquer les conventions personnelles d'Amine : code uniquement dans les fichiers ; modifications ciblées des fichiers existants ; aucune commande Git exécutée par Codex.
- Python 3.12, FastAPI, Pydantic v2, faster-whisper, FFmpeg. Pas de frontend lourd, de cloud ASR ni de base de données.
- Le GO utilisateur du 17 octobre 2026 autorise la réalisation du MVP entier, y compris la vue partagée vidéo/texte synchronisée. Cette autorisation remplace les arrêts entre phases du prompt pour cette livraison.
- Séparer routes, orchestration, média, ASR et exports. Conserver les contrats documentés dans docs/architecture.md.
- Inférence locale sans téléchargement implicite. Le téléchargement du modèle est une commande distincte et explicite.
- Ne pas journaliser les transcriptions ni les contenus médias. Répertoire et identifiants internes indépendants des noms des uploads.
- Vérifier avec Ruff, mypy et pytest ; le test ASR réel est distinct des tests avec moteur simulé.
- Ne pas présenter des vérifications non exécutées comme réussies.
