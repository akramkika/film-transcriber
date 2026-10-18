# Mission : développer un MVP local de transcription de scènes de films

## 1. Contexte et objectif

Tu interviens en tant que **Senior Python Engineer, AI Engineer et Software Architect**.

Construis une application personnelle permettant d'importer une scène de film, d'en extraire l'audio, de transcrire automatiquement les dialogues avec un modèle ASR open source et d'exporter les résultats.

**Contrainte principale : une session de développement d'environ 5 heures.**

L'objectif est un MVP exécutable de bout en bout, avec une base technique professionnelle, testée, maintenable et extensible.

Privilégie systématiquement un parcours utilisateur fonctionnel aux fonctionnalités secondaires.

Travaille directement dans le dépôt fourni. Inspecte son état avant toute modification et respecte les conventions existantes pertinentes.

**Attends mon GO explicite avant de commencer la phase 1.** Une demande de lecture ou de correction de ce prompt autorise uniquement cette lecture ou correction, pas le démarrage du projet. Chaque GO autorise uniquement la phase annoncée ; les phases suivantes nécessitent un nouvel accord explicite.

## 2. Stack technique

| Composant               | Technologie                               |
| ----------------------- | ----------------------------------------- |
| Langage                 | Python 3.12                               |
| Backend                 | FastAPI + Pydantic v2                     |
| Frontend                | HTML, Jinja2, CSS et JavaScript minimal   |
| Reconnaissance vocale   | faster-whisper + CTranslate2              |
| Extraction audio        | FFmpeg / ffprobe                          |
| VAD                     | Silero VAD intégré à faster-whisper       |
| Gestion des dépendances | uv + pyproject.toml + uv.lock             |
| Tests                   | pytest + pytest-cov                       |
| Qualité                 | Ruff + mypy + pre-commit                  |
| CI                      | GitHub Actions, sauf convention existante |
| Stockage                | Système de fichiers local                 |
| Exécution               | Locale, CPU par défaut                    |

Aucune API cloud, base de données ou service externe n'est nécessaire au traitement.

Le téléchargement initial des poids du modèle est autorisé et doit être explicitement documenté. L'inférence doit ensuite pouvoir fonctionner hors ligne avec un modèle déjà présent localement.

Ne présume pas du matériel disponible ni de la présence d'un GPU.

## 3. Fonctionnalités obligatoires

### F1 — Import vidéo

Créer une interface web locale permettant de :

- Sélectionner un fichier MP4, MKV, MOV ou AVI.
- Afficher la vidéo dans un lecteur lorsque le navigateur prend en charge son format.
- Définir facultativement un début et une fin de scène en secondes.
- Lancer la transcription.
- Consulter son état et récupérer les résultats.

La validation doit prendre en compte le type réel du média, sa durée et sa taille, et pas seulement son extension.

Prévoir des limites configurables, avec des valeurs initiales de 500 Mo et 10 minutes de scène.

### F2 — Extraction audio

Utiliser FFmpeg et ffprobe :

- Inspecter les flux du fichier vidéo.
- Extraire la première piste audio compatible.
- Convertir l'audio en WAV, mono, PCM 16 bits, 16 kHz.
- Appliquer le découpage temporel demandé.
- Conserver les métadonnées nécessaires au traitement.

Les commandes externes doivent utiliser `subprocess` sans `shell=True`, avec des arguments explicites, un timeout et une gestion des erreurs.

### F3 — Transcription locale

Créer une interface Python abstraite `ASREngine` afin de pouvoir intégrer plusieurs modèles ultérieurement.

Implémenter uniquement `FasterWhisperEngine` dans ce MVP.

Paramètres par défaut :

- Modèle : `small`, multilingue.
- Exécution : CPU.
- Quantification : INT8.
- Langue : détection automatique, avec choix manuel du français ou de l'anglais.
- VAD activable.
- Timestamps au niveau des segments.
- Beam size configurable.

Charger le modèle une seule fois par processus lorsque cela est possible.

Ne pas prétendre que l'inférence est terminée avant d'avoir intégralement consommé le générateur des segments.

Prévoir des erreurs explicites en cas de modèle absent, de mémoire insuffisante ou de fichier audio invalide.

### F4 — Résultats et exports

Afficher les dialogues avec leurs timestamps.

Une fois la transcription disponible, permettre de lire la vidéo tout en suivant les dialogues dans un panneau de texte dédié. Le segment correspondant à la position courante de la vidéo doit être mis en évidence et rester visible grâce au défilement automatique du panneau.

Permettre l'export en trois formats :

- TXT : transcription textuelle.
- SRT : sous-titres chronométrés.
- JSON : métadonnées, segments, langue détectée et informations de traitement.

Si une plage temporelle a été sélectionnée, les timestamps exportés doivent être relatifs au début de la scène extraite. Conserver également l'offset original dans les métadonnées afin de synchroniser le lecteur vidéo.

Valider notamment le format `HH:MM:SS,mmm` du SRT, les segments vides et l'ordre chronologique.

### F5 — Traitement et suivi

L'interface ne doit pas rester bloquée pendant l'inférence.

Implémenter un mécanisme simple de tâches en arrière-plan avec un nombre limité d'exécutions concurrentes.

États attendus :

`PENDING → PROCESSING → COMPLETED / FAILED`

Prévoir un endpoint de suivi et un polling côté interface.

Un exécuteur local avec stockage des états en mémoire est acceptable pour ce MVP. Documenter clairement ses limites en cas de redémarrage. Ne pas introduire Redis, Celery ou Kubernetes.

## 4. Architecture cible

Proposer une organisation similaire à :

```text
film-transcriber/
├── src/film_transcriber/
│   ├── main.py
│   ├── api/
│   │   ├── routes.py
│   │   └── schemas.py
│   ├── core/
│   │   ├── config.py
│   │   └── logging.py
│   ├── asr/
│   │   ├── base.py
│   │   └── faster_whisper.py
│   ├── services/
│   │   ├── media.py
│   │   ├── transcription.py
│   │   └── jobs.py
│   ├── exporters/
│   │   ├── txt.py
│   │   ├── srt.py
│   │   └── json_exporter.py
│   ├── templates/
│   └── static/
├── tests/
│   ├── unit/
│   └── integration/
├── docs/
│   └── architecture.md
├── .github/workflows/
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── AGENTS.md
├── pyproject.toml
├── uv.lock
└── README.md
```

Cette structure est indicative : adapte-la si une meilleure organisation simple et cohérente est justifiée.

Principes obligatoires :

- Séparation API / logique métier / infrastructure / moteurs ASR.
- Responsabilité unique des composants.
- Dependency injection lorsque pertinente.
- Type hints systématiques.
- Pydantic pour les contrats d'entrée et de sortie.
- Pas de logique métier dans les routes FastAPI.
- Pas de duplication ni d'abstraction prématurée.
- Pas de framework agentique, LLM, LangChain ou LangGraph : ce besoin relève de l'ASR, pas d'un agent IA.

## 5. Standards de développement

### Qualité

- Respect de PEP 8.
- Formatage et lint avec Ruff.
- Typage statique avec mypy.
- Pré-commit configuré.
- Documentation des interfaces publiques et des comportements non évidents.
- Dépendances verrouillées et versions Python compatibles.
- Exceptions métier explicites.
- Utilisation de `pathlib`, de modèles typés et de context managers lorsque pertinents.

Ne pas ajouter Black en parallèle de Ruff Format, sauf si le dépôt l'utilise déjà.

### Tests

Mettre en place :

- Tests unitaires des exporters.
- Tests unitaires des validations et du découpage temporel.
- Tests unitaires du service de transcription avec moteur mocké.
- Tests d'intégration des routes FastAPI.
- Test d'extraction audio sur média synthétique généré localement.
- Test de transitions des états des jobs.
- Test des principaux cas d'erreur.

Viser au moins 80 % de couverture sur la logique métier testable, sans chercher à couvrir artificiellement les bibliothèques tierces.

Ne pas télécharger de gros modèles dans les tests automatisés.

Prévoir un smoke test manuel de transcription réelle lorsqu'un modèle et un échantillon audio sont disponibles.

### Sécurité

- Validation des fichiers et des paramètres temporels.
- Noms de fichiers internes indépendants des noms fournis par l'utilisateur.
- Protection contre le path traversal.
- Protection contre les fichiers excessivement volumineux.
- Timeout des processus FFmpeg.
- Limitation de la concurrence ASR.
- Aucun secret dans le dépôt.
- `.env.example` versionné, `.env` ignoré.
- Ne pas exposer l'application publiquement par défaut.
- Bind sur `127.0.0.1`.
- Nettoyage des fichiers temporaires et possibilité de supprimer explicitement un job.
- Ne pas journaliser les transcriptions complètes ni les contenus audio.

### Observabilité

Ajouter des logs structurés avec au minimum :

- Job ID.
- Étape du pipeline.
- Durée d'extraction.
- Durée d'inférence.
- Durée audio.
- Modèle utilisé.
- Statut et catégorie d'erreur.

Calculer le Real-Time Factor :

`RTF = durée_inférence / durée_audio`

Ajouter un endpoint `/health`.

## 6. Interface utilisateur

Construire une interface simple, sobre et utilisable.

Elle doit comporter :

1. Zone de sélection vidéo.
2. Lecteur vidéo natif lorsque le navigateur prend en charge le média.
3. Sélection des bornes temporelles.
4. Choix de la langue.
5. Bouton de transcription.
6. Indicateur d'état réel du job.
7. Panneau dédié aux segments horodatés, avec mise en évidence du segment actif et défilement synchronisé avec la vidéo.
8. Liens de téléchargement TXT, SRT et JSON.

### Affichage partagé et texte synchronisé

- Sur ordinateur, afficher simultanément la vidéo à gauche et la transcription à droite dans deux panneaux distincts.
- Réserver au texte une zone avec son propre défilement : le suivi des dialogues ne doit pas faire défiler toute la page ni masquer le lecteur vidéo.
- Sur petit écran, adapter les panneaux en les empilant, tout en gardant le lecteur et la zone de texte accessibles.
- Après transcription, mettre en évidence le segment en cours et faire défiler automatiquement le panneau pour le garder visible pendant la lecture.
- Synchroniser le texte sur la position réelle du lecteur, y compris après une pause, une reprise, un déplacement dans la vidéo ou un changement de vitesse. Le texte ne doit pas continuer à avancer lorsque la vidéo est en pause.
- Utiliser les timestamps des segments et l'offset original de la scène pour déterminer le segment actif. En dehors des segments, notamment pendant un silence ou hors de la scène transcrite, ne mettre aucun segment en évidence.
- Un clic sur le timestamp d'un segment doit positionner la vidéo au bon endroit, en tenant compte de l'offset original, lorsque le navigateur prend en charge le média.
- La synchronisation attendue est au niveau des segments ; le surlignage mot à mot n'est pas requis pour ce MVP.
- Avant la fin de la transcription, afficher l'état du traitement dans le panneau de texte. Le défilement synchronisé devient disponible lorsque les résultats sont prêts.

Vérifier la mise en évidence et le défilement pendant la lecture, la pause, la reprise, la navigation avant/arrière, les silences et la lecture à vitesse modifiée, notamment avec une scène dont le début est différent de zéro.

Pas de React, Next.js ni de framework frontend lourd pour cette première version.

Ne pas inventer de pourcentage de progression ASR si le backend ne fournit pas de mesure fiable.

## 7. Méthode de travail — session de 5 heures

Après le GO explicite pour la phase concernée, développe de manière incrémentale. Effectue une vérification après chaque phase, puis arrête-toi pour obtenir la validation de l'utilisateur et son GO pour la suivante. Le cycle de validation détaillé figure en section 11.

### Phase 1 — Cadrage, architecture, contrats et maquette HTML (30 min)

- Inspecter le dépôt, les fichiers existants et les instructions AGENTS.md.
- Identifier le système d'exploitation, Python, FFmpeg et les dépendances disponibles.
- Rédiger un plan technique court.
- Documenter la structure proposée, les dépendances, les outils de qualité et la configuration prévue.
- Définir les contrats et les interfaces métier dans la documentation.
- Créer une maquette HTML statique dans un dossier dédié, avec la vue partagée vidéo/texte et des données fictives clairement signalées.
- Présenter les critères d'acceptation et les décisions à valider, sans implémenter de code applicatif Python.

### Phase 2 — Pipeline audio + ASR (60 min)

- Initialisation de la structure applicative, des outils de qualité et de la configuration validés en phase 1.
- Extraction audio.
- Inspection média.
- Abstraction ASREngine.
- Implémentation faster-whisper.
- Transcription des segments.
- Gestion des erreurs.

**Livrable intermédiaire :** transcription possible depuis un fichier local avec une commande Python, si modèle disponible.

### Phase 3 — API et application web (75 min)

- Upload.
- Validation.
- Jobs et suivi d'état.
- Page HTML.
- Lecteur vidéo.
- Affichage des résultats dans le panneau de texte, avec mise en évidence et défilement synchronisés avec la vidéo.
- Exports.

**Livrable intermédiaire :** parcours utilisateur complet sur `localhost`.

### Phase 4 — Tests et fiabilisation (60 min)

- Tests unitaires.
- Tests d'intégration.
- Mock ASR.
- Test FFmpeg synthétique.
- Sécurité des fichiers.
- Gestion des erreurs.
- Ruff, mypy et couverture.

### Phase 5 — Documentation et CI (45 min)

- README complet.
- Instructions d'installation Windows, Linux et macOS.
- Prérequis FFmpeg.
- Documentation du téléchargement initial du modèle.
- Commandes de démarrage.
- Diagramme d'architecture.
- Workflow CI.
- AGENTS.md pour les futures sessions Codex.

### Phase 6 — Validation finale (30 min)

- Exécuter les contrôles qualité.
- Tester les routes et le pipeline.
- Effectuer un smoke test ASR réel si les ressources le permettent.
- Identifier les limitations restantes.
- Corriger les problèmes bloquants.
- Produire un bilan de livraison.

Les temps sont des budgets indicatifs, pas des garanties. Si une étape prend du retard, réduire le périmètre secondaire plutôt que sacrifier le parcours fonctionnel.

## 8. Hors périmètre

Ne pas développer dans cette session :

- Fine-tuning des modèles.
- Entraînement ASR from scratch.
- Reconnaissance des personnages par la voix.
- Diarisation multi-locuteurs.
- Séparation avancée voix / musique.
- Traduction multilingue.
- Streaming microphone.
- Support multi-utilisateurs.
- Authentification et comptes.
- Base de données externe.
- Déploiement Kubernetes.
- Traitement distribué.
- Support complet de plusieurs moteurs ASR.

L'architecture peut prévoir leur intégration future, sans en implémenter les composants.

## 9. Critères d'acceptation

Le MVP sera considéré comme livré lorsque :

- [ ] L'application démarre localement avec une commande documentée.
- [ ] Un utilisateur peut importer une scène vidéo compatible.
- [ ] FFmpeg extrait correctement l'audio.
- [ ] faster-whisper peut transcrire les dialogues avec un modèle local.
- [ ] Les segments et leurs timestamps sont affichés.
- [ ] La vidéo et la transcription disposent de deux panneaux visibles simultanément sur ordinateur.
- [ ] Le segment actif est mis en évidence et le texte défile automatiquement dans son panneau au rythme de la vidéo.
- [ ] Le suivi reste synchronisé après pause, reprise, navigation et changement de vitesse, y compris avec un offset de scène non nul ; aucun segment n'est actif pendant les silences ou hors de la scène transcrite.
- [ ] Un clic sur un timestamp positionne correctement la vidéo en tenant compte de l'offset original, lorsque le média est lisible par le navigateur.
- [ ] TXT, SRT et JSON sont exportables.
- [ ] L'application signale correctement les erreurs.
- [ ] Les tests unitaires et d'intégration passent.
- [ ] Ruff et mypy passent.
- [ ] Le README permet de reproduire l'installation.
- [ ] Les fichiers et modèles ne sont pas envoyés à une API externe pendant le traitement.

Les critères nécessitant un modèle ou un média indisponible doivent être déclarés **non vérifiés**, jamais artificiellement validés.

## 10. Vérifications et bilan de livraison

Avant tout démarrage, présente brièvement le périmètre de la phase 1 et attends mon GO explicite. L'inspection du dépôt, le cadrage détaillé et la maquette font partie de cette phase et commencent après cet accord.

Après autorisation, réalise uniquement la phase concernée, selon le cycle de validation décrit en section 11. Aucun enchaînement automatique des phases n'est autorisé.

Après chaque phase :

1. Vérifie ce qui fonctionne.
2. Exécute les tests concernés.
3. Corrige les régressions.
4. Mets à jour la documentation utile.
5. Présente le rapport de validation, puis arrête-toi jusqu'à mon accord explicite pour la phase suivante.

Respecte l'historique Git existant et utilise des modifications ciblées. Toutes les commandes Git sont exécutées par l'utilisateur. Codex ne touche jamais à `git config` et n'effectue aucune opération Git destructive.

**Objectif final, au terme des phases explicitement autorisées : disposer d'une application locale capable de transcrire réellement une scène de film.** Cet objectif ne permet jamais de contourner les validations humaines.

Ne masque pas une fonctionnalité incomplète derrière des données simulées. Seule la maquette statique de phase 1 peut présenter des données fictives, clairement identifiées comme telles.

À la livraison finale, après les phases autorisées, fournis :

- Les fonctionnalités réellement implémentées.
- L'architecture retenue.
- Les commandes exactes d'installation, de lancement et de test.
- Les résultats des contrôles qualité.
- Les limites et problèmes connus.
- Les trois améliorations les plus pertinentes pour la prochaine session.

## 11. Méthodologie de développement — Validation humaine obligatoire

### Règle fondamentale : développement incrémental avec validation

**INTERDICTION ABSOLUE DE DÉVELOPPER L'APPLICATION EN UNE SEULE EXÉCUTION.**

Le développement doit être découpé en phases indépendantes, vérifiables et validées explicitement par l'utilisateur.

La session de 5 heures représente un budget de développement estimatif, **pas une autorisation d'exécuter automatiquement toutes les phases**.

Codex doit respecter le cycle suivant :

1. Présenter le périmètre de la phase.
2. Expliquer les choix techniques et les hypothèses.
3. Définir les contrats, les fichiers concernés et les tests attendus.
4. Attendre le GO explicite autorisant cette phase, y compris pour la phase 1.
5. Implémenter uniquement le périmètre autorisé.
6. Exécuter les tests et les vérifications.
7. Présenter les résultats et les modifications.
8. **S'arrêter et attendre la validation humaine avant toute nouvelle phase.**

Une validation technique automatique ne remplace jamais la validation de l'utilisateur.

Pour la phase 1, la présentation préalable reste un bref périmètre fondé sur ce prompt. L'architecture détaillée, les contrats et la maquette constituent les livrables à produire après le GO ; ils sont ensuite soumis à validation avant la phase 2.

### 11.1. Validation avant développement

Avant d'écrire du code applicatif, Codex doit fournir :

- L'architecture technique proposée.
- Les composants et leurs responsabilités.
- Les dépendances nécessaires.
- Les contrats entre modules.
- Le parcours fonctionnel utilisateur.
- Les risques techniques et les limites du MVP.
- Le découpage des développements.
- Les critères d'acceptation de chaque phase.

Proposer également une maquette HTML statique de l'interface, dans un dossier dédié, afin de valider l'expérience utilisateur avant de développer le backend.

Cette maquette peut employer des données fictives, clairement identifiées comme telles. Elle ne doit pas être présentée comme une fonctionnalité opérationnelle.

**Attendre explicitement la validation de l'architecture et de l'interface avant d'implémenter le pipeline ASR.**

### 11.2. Développement par petits incréments

Pendant une phase autorisée :

- Développer une fonctionnalité cohérente à la fois.
- Éviter les changements massifs sur plusieurs composants.
- Définir le comportement attendu avant l'implémentation.
- Écrire les tests associés à chaque fonctionnalité.
- Exécuter les tests concernés immédiatement.
- Contrôler les régressions après chaque modification.
- Conserver le projet dans un état exécutable autant que possible.
- Réaliser les refactorings de façon ciblée, idéalement un fichier à la fois.
- Éviter toute surarchitecture ou fonctionnalité non demandée.

Les corrections nécessaires pour terminer la phase autorisée peuvent être réalisées sans nouvelle validation, à condition de rester strictement dans son périmètre.

### 11.3. Contrôles qualité obligatoires

À la fin de chaque phase, exécuter les contrôles applicables :

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run pytest -v
uv run pytest --cov=film_transcriber --cov-report=term-missing
```

Ces commandes doivent être adaptées à la configuration réellement installée. Ne pas masquer une erreur en supprimant un test ou en désactivant une règle.

En phase 1, vérifier la cohérence des documents et l'affichage de la maquette. Les contrôles Python qui ne s'appliquent pas encore doivent être indiqués « non applicables à cette phase », sans les présenter comme réussis et sans implémenter le backend pour les exécuter.

Vérifier également :

- Le bon fonctionnement des composants développés.
- Les contrats d'entrée et de sortie.
- La gestion des exceptions.
- Les cas limites.
- L'absence de régression.
- La cohérence des dépendances.
- Les éventuels problèmes de sécurité.
- La maintenabilité du code.

Viser 80 % de couverture sur la logique métier testable. Ne pas inventer de résultats ni considérer un test non exécuté comme réussi.

Si un contrôle échoue, corriger dans le périmètre autorisé et relancer les vérifications. Si le problème persiste, le signaler avant toute progression.

### 11.4. Rapport de validation obligatoire

À la fin de chaque phase, Codex doit présenter le rapport suivant :

**Phase X — Rapport de validation**

| Élément | Résultat attendu |
|---|---|
| Objectif | Fonctionnalité réalisée |
| Fichiers | Fichiers créés ou modifiés |
| Architecture | Décisions prises et justification |
| Tests unitaires | Nombre exécuté, réussis, échoués |
| Tests d'intégration | Résultats réels |
| Qualité | Ruff, mypy, couverture |
| Sécurité | Contrôles effectués |
| Démonstration | Commandes ou procédure de vérification |
| Limitations | Points non terminés ou non vérifiés |
| Prochaine étape | Proposition, sans exécution |

Fournir les commandes permettant à l'utilisateur de reproduire les tests.

Lorsque l'interface évolue, préciser comment visualiser et tester les modifications.

Utiliser uniquement des résultats réellement observés.

### 11.5. Validation humaine — STOP obligatoire

À la fin de chaque phase, afficher :

**PHASE TERMINÉE — EN ATTENTE DE VALIDATION UTILISATEUR**

Puis demander :

"Souhaites-tu valider cette phase, demander des corrections ou revoir certains choix avant de continuer ?"

Ne pas commencer la phase suivante tant que l'utilisateur n'a pas explicitement donné son accord.

La validation des livrables ne vaut pas, à elle seule, autorisation de commencer la phase suivante : demander également un GO explicite pour cette phase. Un même message utilisateur peut valider la phase terminée et autoriser la suivante.

Un silence, un succès des tests ou l'absence de problème ne constitue pas une autorisation.

### 11.6. Découpage de la session

| Phase | Objectif | Budget indicatif |
|---|---|---|
| 1 | Cadrage, architecture, contrats et maquette HTML | 30 min |
| 2 | Extraction audio FFmpeg + moteur ASR local | 60 min |
| 3 | API FastAPI + interface web + exports | 75 min |
| 4 | Tests approfondis, sécurité et fiabilisation | 60 min |
| 5 | CI, documentation et préparation de livraison | 45 min |
| 6 | Validation fonctionnelle finale et corrections | 30 min |

**Chaque phase constitue un point d'arrêt obligatoire.**

Les vérifications essentielles doivent aussi être réalisées pendant chaque phase, sans être reportées à la phase 4.

Si une phase dépasse son budget, signaler le dépassement. Ne pas sacrifier la qualité ou poursuivre sans validation pour respecter artificiellement la durée totale.

## 12. Instructions impératives pour Codex

### Priorités

1. Code fonctionnel plutôt que code volumineux.
2. Architecture simple plutôt que surarchitecture.
3. Tests vérifiables plutôt que promesses de fonctionnement.
4. Modifications ciblées plutôt que refactoring massif.
5. Validation humaine plutôt qu'exécution automatique.
6. Traçabilité des décisions et des résultats.

### Gestion Git

- Toutes les commandes Git sont exécutées par l'utilisateur ; Codex peut proposer les commandes utiles sans les lancer.
- Ne jamais modifier `git config` ni effectuer d'opération Git destructive.
- Ne jamais écraser le travail existant.
- Respecter les changements non commités.
- Suggérer de petits commits cohérents à l'utilisateur lorsque pertinent.
- Ne jamais effectuer de déploiement sans autorisation explicite.

### Comportements interdits

- Commencer la phase 1 sans GO explicite ou développer une nouvelle phase sans son autorisation propre.
- Introduire des fonctionnalités hors périmètre.
- Modifier silencieusement l'architecture validée.
- Masquer un test en échec.
- Ignorer une erreur de typage ou de linting.
- Désactiver des contrôles pour obtenir artificiellement un résultat positif.
- Présenter un mock comme une intégration réelle.
- Affirmer qu'une fonctionnalité a été testée sans l'avoir exécutée.
- Passer à la phase suivante parce que les tests sont verts.
- Effectuer des changements destructeurs ou irréversibles sans validation.

### Première action attendue

**Présente brièvement le périmètre de la phase 1, puis attends mon GO avant de commencer.** Une demande de lecture ou de correction du prompt ne constitue pas ce GO.

Après ce GO, réalise exclusivement la phase 1 : cadrage technique, proposition d'architecture, contrats documentés et maquette HTML statique.

Ne développe pas encore le moteur ASR, les services métier ou les endpoints applicatifs.

Présente les livrables de cette première phase, les vérifications réalisées et les décisions à valider.

**Arrête-toi après la phase 1 et attends explicitement mon GO avant de continuer.**
