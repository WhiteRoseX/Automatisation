# TelePilot 0.3.1 — correctifs ciblés

Cette version conserve l’architecture PySide6 + Telethon + SQLite et ne rajoute **aucune dépendance**.

## Changements

- Correction du traitement des interruptions réseau dans `core/engine.py` : `ConnectionError` et `TimeoutError` héritent de `OSError` en Python. Les erreurs réseau antérieures à l’envoi restent réessayables ; celles qui surviennent après le début de l’envoi placent la tâche en état incertain (`unknown`) pour empêcher les doublons. Les vraies erreurs de fichiers restent des échecs.
- Le statut source expose désormais `can_attempt_download` : l'accès peut être vérifié automatiquement quand l’utilisateur clique « Télécharger », même si l’ancienne vérification est périmée.
- La fenêtre d’importation utilise cet indicateur explicite, plus une analyse fragile des textes d'erreur pour activer ou désactiver le bouton. Les sources protégées ou sans droits restent bloquées.
- Tests supplémentaires pour les erreurs réseau, les vrais problèmes de fichier et les statuts des sources.

## Installer

Sauvegarder le dossier initial. Pour la mise à jour, remplacer uniquement les fichiers modifiés indiqués dans `TelePilot-corrections.patch` ou utiliser l’archive source complète. **Ne pas effacer** le dossier local des sessions et données de TelePilot.

Avec l'environnement Python déjà installé sur le Mac :

```bash
python -m unittest discover -s tests -v
python -m telepilot
```

## Validation dans cet environnement

`31` tests du noyau et du nouveau statut des sources passent sur Python 3.13. `compileall` passe. Les tests Qt et la connexion Telegram réelle n'ont pas pu être exécutés ici : PySide6 et Telethon ne sont pas installés dans l'environnement d'audit. Faire ces vérifications sur le Mac.
