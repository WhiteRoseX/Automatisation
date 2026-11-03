# Migration 0.4 -> 0.5

La 0.4 utilisait `QWebEngineView`: elle n'était pas un vrai site local. La 0.5 retire Qt au lancement, sert les fichiers HTML/CSS/JS sur `http://127.0.0.1` et expose les actions par des routes HTTP strictement locales. Aucune nouvelle dépendance serveur.

Les modules `telepilot/core`, `telepilot/service.py`, `telepilot/telegram/client.py`, `telepilot/security.py` et `telepilot/config.py` sont conservés. Les anciens écrans Qt ont été retirés, ainsi que les tests purement Qt.

La 0.5 n'a pas encore été testée contre un compte Telegram réel, ni sur macOS dans cet environnement. Le comportement du service Python reste soumis aux limites de Telegram et à la configuration de votre compte.
