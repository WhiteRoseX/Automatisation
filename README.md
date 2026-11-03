# TelePilot 0.6 — Studio local

Application web locale pour gérer vos canaux et groupes Telegram, vos médias, vos publications et vos partenariats. Le moteur reste en **Python + Telethon + SQLite**. L'interface fonctionne en **HTML + CSS + JavaScript natif**, sans Node, React, Electron, CDN ou hébergement distant.

## Démarrage sur macOS

Prérequis : Python 3.13 ou 3.14, compte Telegram et identifiants API depuis `https://my.telegram.org`.

Depuis le dossier extrait :

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m telepilot
```

TelePilot ouvre votre navigateur à une URL **`127.0.0.1` sur un port libre**. Gardez le Terminal ouvert. Pour fermer, faites `Ctrl+C`. Ne tentez pas de vous connecter via une URL `/api/state` ouverte directement : la session locale est établie automatiquement par le lien de démarrage à usage unique.

Si vous utilisez déjà TelePilot 0.5, sauvegardez et recopiez **uniquement** votre dossier `.telepilot/` dans le nouveau projet avant le lancement ; il contient les sessions, médias et la base de données. **Ne publiez jamais ce dossier ni les fichiers `.session`.** Si vous lancez la nouvelle version sans recopier vos données, une nouvelle base locale vide sera créée.

## Parcours principaux

- **Connexion** : lorsque Telegram est déconnecté, l'interface se limite aux étapes d'authentification.
- **Mon réseau** : vraies photos de profil si accessibles, groupes/canaux, création privée d'un canal ou d'un supergroupe, synchronisation, accès aux médias et aux publications.
- **Contenus** : vos canaux et groupes synchronisés, sans ajout préalable de lien public pour les utiliser comme source. Les protections Telegram et les permissions d'utilisation restent respectées.
- **Médiathèque** : fichiers photo et vidéo locaux en aperçus natifs, flou visuel réglable (0–32 px), révélation par clic sans confirmation. Les vidéos sont servies par plages d'octets pour éviter de les charger en mémoire.
- **Partenaires** : conversations Telegram existantes des partenaires enregistrés ; réponses manuelles, pas de démarchage automatique.
- **Diffusion, analyses, tâches** : le moteur historique reste en place.

La création de canaux et la messagerie utilisent l'API Telegram via Telethon. La création, la récupération des profils et l'envoi de messages doivent être validés sur votre vrai compte. La messagerie n'ouvre **pas** automatiquement de nouvelles conversations avec des inconnus ; elle exige une discussion déjà existante.

## Modifier le design

- `telepilot/web/index.html` : shell et identité visuelle.
- `telepilot/web/assets/style.css` : styles de base historiques.
- `telepilot/web/assets/polish.css` : ajustements hérités.
- `telepilot/web/assets/studio.css` : direction artistique 0.6 (palette graphite / sauge, glassmorphism, animations, responsive).
- `telepilot/web/assets/app.js` : pages et événements ; un rafraîchissement du navigateur suffit pour les changements CSS/JS (le serveur n'a pas besoin d'être redémarré).
- `telepilot/local_web/server.py` : routes HTTP locales et médias authentifiés.
- `telepilot/telegram/client.py` et `telepilot/service.py` : API Telegram et logique métier.

## Sécurité et limites

Le serveur ne se lie qu'à `127.0.0.1`, utilise un cookie HttpOnly + un jeton initial à usage unique, contrôle les commandes, l'origine et les chemins des médias. Les originaux des aperçus sensibles ne sont transférés **qu'au navigateur local authentifié** ; le flou est une présentation CSS, pas une transformation du fichier. Ne partagez pas la session locale ou votre Mac avec des personnes non autorisées.

Les médias tiers doivent pouvoir être exploités légalement : l'accès technique ne confère pas le droit de republication. Les restrictions Telegram ne sont pas contournées. Certaines vidéos peuvent ne pas disposer d'un aperçu dans le navigateur si le codec n'est pas pris en charge.

## Tests

```bash
python -m unittest discover -s tests -v
```

**80 tests unitaires et HTTP locaux réussis** dans l'environnement de développement, avec Telethon 1.42.0. Les écrans et les principales interactions ont également été vérifiés avec Chromium sur des données fictives. Aucune connexion réelle à Telegram ni publication n'a été testée dans cet environnement.
