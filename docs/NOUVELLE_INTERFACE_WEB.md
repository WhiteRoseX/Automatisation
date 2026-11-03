# TelePilot 0.4 — Interface web locale

## Ce qui a changé

- **HTML, CSS et JavaScript natifs** : aucune dépendance Node.js/React, aucun CDN.
- **PySide6 QtWebEngine** affiche les fichiers locaux dans la fenêtre macOS.
- **QWebChannel** fait passer les commandes vers l'ancien `Bridge`, `ApplicationService`, `Telethon` et SQLite.
- Les modules `core/`, `telegram/`, `service.py`, `database.py` sont conservés.
- L'ancienne interface Qt Widgets est conservée comme filet de sécurité via `--legacy-ui`.

## Démarrer

```bash
.venv/bin/python -m telepilot
```

Le script `Lancer TelePilot.command` marche aussi, sans autre modification.

Pour revenir temporairement à l'ancienne interface :

```bash
.venv/bin/python -m telepilot --legacy-ui
```

Pour vérifier les dépendances existantes sur le Mac :

```bash
.venv/bin/python -c 'from PySide6.QtWebEngineWidgets import QWebEngineView; from PySide6.QtWebChannel import QWebChannel; print("Qt WebEngine disponible")'
```

Si l'import échoue, réinstaller les dépendances telles que définies dans le projet :

```bash
.venv/bin/python -m pip install -r requirements.txt
```

## Préserver les données

**Ne supprimez pas `.telepilot/live`**. Il contient la base SQLite, les médias et les sessions locales.

Le ZIP source livré n'inclut **ni `.venv`, ni `.git`, ni `.telepilot`, ni token, ni fichier `.session`**.

Pour mettre à jour votre projet déjà installé, sauvegardez-le, puis remplacez les dossiers de code `telepilot/`, `docs/` et les fichiers `pyproject.toml` et `README.md`. Gardez le dossier `.telepilot/` et votre `.venv/` existants.

## Dossiers importants

- `telepilot/web/index.html` : squelette de l'interface.
- `telepilot/web/assets/style.css` : thème sombre, glassmorphism, états et layouts.
- `telepilot/web/assets/app.js` : navigation, événements, cartes et formulaires.
- `telepilot/web/window.py` : fenêtre Qt WebEngine et passerelle QWebChannel sécurisée.
- `telepilot/__main__.py` : sélection de l'interface web par défaut ou de l'ancienne UI avec `--legacy-ui`.

## Limites et validations

La couche backend reste inchangée : la connexion Telegram, les droits, les protections des canaux, la file d'envois et les règles de téléchargement utilisent les mêmes validations Python qu'avant.

- L'interface affiche les photos locales compatibles en miniature, si la confidentialité le permet. Les vidéos utilisent une vignette générique (pas de transcodage ajouté).
- Le sélecteur distant liste les publications et leurs légendes ; il n'affiche pas encore les miniatures des médias non téléchargés.
- Le module « Rédaction » propose des modèles locaux, **pas une intelligence artificielle connectée**.
- Les statistiques montrent les données disponibles via le backend, sans inventer de valeurs.
- La nouvelle interface n'a pas pu être testée avec une vraie session Telegram dans l'environnement de construction. Vérifiez les fonctions sensibles sur macOS avant tout usage réel.

## Architecture de sécurité

- Pas de serveur HTTP, pas de chargement de ressources web distantes.
- Politique CSP restrictive, pas de scripts tiers.
- La passerelle Python n'expose qu'une liste de commandes autorisées : pas d'exécution Python arbitraire.
- Les fichiers locaux ouverts via la passerelle sont vérifiés par rapport au stockage de TelePilot.
- L'interface ne conserve pas les identifiants API ni le mot de passe 2FA dans le navigateur.

Les fichiers existants de documentation d'architecture décrivent encore certains écrans Qt Widgets de l'interface précédente ; ce fichier prime pour la version web.
