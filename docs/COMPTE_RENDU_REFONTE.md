# Compte rendu de la première refonte

## Résultat

TelePilot garde son architecture Python, PySide6, Telethon et SQLite. La navigation comporte six espaces avec sous-pages, plus un accès séparé au compte. Les actions de connexion apparaissent dans l'ordre API → numéro → code → mot de passe 2FA si Telegram le demande. Après une connexion enregistrée, le mode réel restaure automatiquement la session au prochain lancement et ouvre l'accueil. L'API hash est conservé dans le trousseau macOS lorsque la case, cochée par défaut, reste active ; le fichier de session Telethon reste dans le dossier de données privé. Aucun code ni mot de passe 2FA n'est sauvegardé.

La synchronisation distingue canaux de diffusion, supergroupes et groupes classiques et ignore les conversations privées. Le réseau peut être organisé localement en hiérarchie, sans action distante implicite. Les liens publics accessibles peuvent être ajoutés et vérifiés avant tout usage des contenus. Chaque page dispose de l'aide « ? » et de l'inspection locale « Curseur ? ».

## Diagnostic du `TypeError`

Le cas reproductible sans compte réel est un appel à `send_code_request` avec un numéro vide : Telethon 1.42.0 le convertit en `None`, puis `telethon/tl/tlobject.py:serialize_bytes` lève `TypeError: bytes or str expected, not <class 'NoneType'>`. TelePilot valide maintenant le numéro avant Telethon et n'affiche l'étape du numéro qu'après configuration des identifiants API. Les erreurs imprévues écrivent une traceback complète en termes de fichiers, lignes, fonctions et classes d'exception, sans messages bruts, variables locales ni secrets.

Le journal historique ne contenait pas de traceback. La reproduction identifie une cause réelle et corrigée, mais ne prouve pas que le clic exact de l'utilisateur a emprunté ce chemin. La configuration seule a été vérifiée avec la version installée de Telethon et des valeurs fictives, sans reproduire ce `TypeError`.

## Fichiers modifiés ou ajoutés

| Domaine | Fichiers |
|---|---|
| Démarrage, configuration et services | `telepilot/__init__.py`, `telepilot/__main__.py`, `telepilot/service.py`, `telepilot/diagnostics.py` |
| Modèle et données | `telepilot/core/models.py`, `telepilot/core/database.py`, `telepilot/core/network.py` |
| Telegram et démonstration | `telepilot/telegram/client.py`, `telepilot/telegram/demo.py`, `telepilot/demo.py` |
| Interface | `telepilot/ui/bridge.py`, `telepilot/ui/settings.py`, `telepilot/ui/help.py`, `telepilot/ui/help_registry.py`, `telepilot/ui/navigation.py`, `telepilot/ui/network.py`, `telepilot/ui/window.py`, `telepilot/ui/widgets.py`, `telepilot/ui/pages.py`, `telepilot/ui/publications.py`, `telepilot/ui/library.py`, `telepilot/ui/theme.py` |
| Tests | `tests/test_auth.py`, `tests/test_auth_ui.py`, `tests/test_diagnostics.py`, `tests/test_network.py`, `tests/test_navigation_help.py`, `tests/test_ui.py` |
| Projet et documentation | `.gitignore`, `pyproject.toml`, `README.md`, `docs/ARCHITECTURE.md`, `docs/ETAT_DU_PROJET.md`, `docs/AUDIT_REFONTE.md`, `docs/VALIDATION_TELEGRAM.md`, `docs/COMPTE_RENDU_REFONTE.md` |

Les lanceurs `.command` restent disponibles. Aucune dépendance n'a été ajoutée.

## Vérifications effectuées

- Suite complète avant le dernier ajout de restauration automatique : 69 tests, tous réussis ; elle couvre notamment les étapes de connexion simulées, Telethon installé sans réseau, la migration SQLite, les groupes, la navigation et l'aide.
- Après cet ajout : test ciblé de démarrage et restauration automatique avec transport Telegram simulé, réussi. Aucun compte Telegram réel n'a été utilisé.
- Démarrage macOS natif avec un dossier de test vide et captures de l'accueil et du réseau de démonstration effectués avant cet ajout. L'utilisateur effectue la recette réelle.

## Vérifier sur son Mac

1. Fermer toute ancienne instance de TelePilot, puis double-cliquer sur `TelePilot.command` du Bureau ou sur `Lancer TelePilot.command` dans le dossier du projet.
2. Si c'est la première connexion, saisir API ID et API hash en laissant cochée la conservation dans le trousseau, puis suivre les étapes numéro, code et 2FA uniquement si demandé.
3. Une fois connecté, fermer normalement TelePilot et rouvrir le même lanceur. Le compte doit apparaître connecté sans redemander code ni mot de passe, et l'accueil doit s'ouvrir.
4. Si le trousseau n'avait pas été activé auparavant, ressaisir l'API hash une fois avec la case cochée. Si la session a été révoquée dans Telegram, une nouvelle authentification est nécessaire.
5. En cas d'erreur, ouvrir **Compte & paramètres → Ouvrir le journal de diagnostic**, puis transmettre la traceback expurgée. Le journal local est aussi dans `.telepilot/live/logs/telepilot.log`.

La découverte distante étendue, les invitations, les demandes d'adhésion et les fonctions avancées de partenariat ou d'IA restent des développements ultérieurs ; cette intervention conserve des actions locales explicites et vérifiables.
