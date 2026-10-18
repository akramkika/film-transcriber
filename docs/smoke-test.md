# Recette manuelle et transcription réelle

Cette procédure décrit des vérifications à exécuter. Elle n'est pas un compte rendu de tests déjà réussis. Consigner séparément les commandes, la date, le matériel, le modèle et les résultats effectivement observés.

## Préparer un test réel

1. Installer l'environnement avec `uv sync --locked` et FFmpeg/ffprobe.
2. Exécuter `uv run film-transcriber doctor`.
3. Si le modèle manque, exécuter explicitement `uv run film-transcriber download-model`. Aucun téléchargement ne doit survenir au lancement d'une transcription.
4. Choisir une courte vidéo locale contenant quelques phrases clairement audibles. Un MP4 H.264/AAC facilite la validation du lecteur. Utiliser un contenu qu'il est possible de traiter localement.
5. Préparer une transcription de référence humaine pour comparer les mots reconnus, sans la placer dans les journaux applicatifs.

Pour vérifier la coupure temporelle et la synchronisation, choisir si possible une vidéo de plus de 20 secondes dont une phrase se trouve après la dixième seconde. Pour un premier essai, une scène de 10 à 30 secondes suffit.

## Parcours web

Lancer `uv run film-transcriber serve`, puis ouvrir [http://127.0.0.1:8000](http://127.0.0.1:8000).

| Vérification | Résultat attendu |
| --- | --- |
| Sélection d'une vidéo lisible | Nom et lecteur disponibles ; l'interface reste utilisable |
| Début et fin valides | La plage est acceptée et correspond à la scène voulue |
| Lancement | Un état en attente ou en traitement apparaît sans figer la page |
| Fin du traitement | Les segments et les liens d'export sont disponibles |
| Lecture | Le segment actif est surligné et défile dans le panneau texte |
| Pause et reprise | La sélection correspond toujours au temps vidéo |
| Recherche dans la vidéo | Le segment actif change après déplacement de la tête de lecture |
| Clic sur un dialogue | La vidéo se positionne sur le début du segment, offset de scène compris |
| Plage débutant après zéro | La vidéo utilise le temps original ; le premier export est relatif à la scène |
| Passage sans voix | Aucun segment hors intervalle n'est surligné |
| Fin de la scène | Le panneau reste cohérent avec les horodatages disponibles |
| Fenêtre étroite | La vidéo et le panneau texte restent consultables |

La synchronisation se fait sur les segments produits par le modèle. Elle ne garantit pas une correspondance mot par mot. Vérifier à l'écoute qu'une phrase est affichée au bon moment et noter tout décalage perceptible.

## Vérifier les exports

- TXT : fichier UTF-8 avec les dialogues dans l'ordre.
- SRT : blocs numérotés, horodatages `HH:MM:SS,mmm`, début inférieur à la fin, chronologie sans chevauchement.
- JSON : métadonnées de modèle et de scène, `scene_start_seconds`, langue, segments et métriques. Les segments doivent correspondre au texte visible.
- Avec une scène commençant à 10 secondes, un segment situé 2 secondes après le début de scène doit correspondre à environ 12 secondes dans la vidéo.
- Comparer le texte reconnu à la référence humaine. Signaler les omissions ou substitutions ; un export valide ne suffit pas à établir la qualité ASR.

## Parcours CLI

```shell
uv run film-transcriber transcribe "ma-video.mp4" --start 10 --end 25 --language fr --output artifacts/recette
```

Vérifier que les trois exports apparaissent dans le sous-dossier UUID annoncé et qu'ils décrivent uniquement la plage sélectionnée. Les messages console doivent porter sur les étapes et métriques, sans afficher les dialogues.

## Cas d'erreur

| Cas | Résultat attendu |
| --- | --- |
| Modèle absent du cache | Erreur explicite invitant au téléchargement manuel, aucune connexion implicite |
| FFmpeg/ffprobe introuvable | Diagnostic explicite, sans traceback utilisateur contenant les médias |
| Fichier sans piste audio | Échec lisible ; la page permet de sélectionner une autre vidéo |
| Fichier vide, corrompu ou faux MP4 | Rejet lors de la validation ou de l'inspection réelle |
| Fin inférieure ou égale au début | Rejet de la plage |
| Début au-delà de la vidéo | Rejet de la plage |
| Fichier dépassant la limite configurée | Rejet avant l'inférence |
| Scène dépassant la durée maximale | Rejet avec demande de réduction de la plage |
| Vidéo lisible par FFmpeg mais pas par le navigateur | Transcription possible ; aperçu indisponible expliqué |
| Redémarrage du serveur | Anciens états non récupérés ; fichiers déjà écrits toujours présents |

## Vérifier le mode hors ligne

Après installation et téléchargement réussis, couper l'accès réseau, relancer le serveur et traiter la même courte vidéo. Le test est réussi uniquement si une nouvelle transcription se termine avec les poids déjà présents. Ne pas confondre le téléchargement des dépendances par `uv` avec l'inférence ; l'environnement doit avoir été installé au préalable.

## Trace des résultats

Pour chaque session de recette, noter : date, système, processeur, RAM, version Python, versions FFmpeg et faster-whisper, modèle, réglages CPU/INT8, durée de la scène, durée d'extraction, durée d'inférence et ratio temps réel (RTF). Un RTF inférieur à 1 signifie une inférence plus rapide que la durée audio.

Séparer clairement : tests automatiques avec moteur simulé ; tests FFmpeg réels ; reconnaissance Whisper réelle ; contrôle visuel du navigateur. Ne déclarer aucune de ces catégories réussie sans l'avoir exécutée.
