# Audit et première refonte des workflows

## État avant intervention

L'application utilise PySide6, une boucle asyncio dans un thread dédié, Telethon 1.42.0 et SQLite. Le noyau métier ne dépend pas de Qt. Les tâches, droits, médias, partenaires et observations sont persistants. Les tests existants couvrent le moteur et l'interface de démonstration. La correction de connexion en cours ajoute des tests de transport simulé et de parcours Qt, sans compte réel.

La navigation affichait douze entrées au même niveau : tableau de bord, canaux, sources, médiathèque, publications, automatisations, statistiques, partenaires, échanges, assistant, surveillance et paramètres. Plusieurs transitions utilisaient des indices numériques de pages ; un déplacement risquait d'ouvrir la mauvaise vue. Le bouton global d'activation pouvait lancer publications **et** importations sans montrer la file concernée.

L'adaptateur `TelethonGateway.channels()` sélectionnait seulement `types.Channel` avec `broadcast=True`. Les supergroupes (`megagroup`) et groupes classiques (`Chat`) étaient exclus. Les conversations privées étaient également exclues, ce qui doit être conservé. Le modèle et la table `channels` ne conservaient ni type, ni rôle, ni visibilité ; `can_post` ne permettait pas de distinguer propriétaire, administrateur et membre.

La bibliothèque de widgets ne proposait ni aide commune aux pages, ni registre de descriptions, ni inspection. Les états vides étaient principalement des tableaux sans lignes.

## Navigation cible de cette intervention

| Espace | Sous-pages | Flux principal |
|---|---|---|
| Accueil | Vue d'ensemble, Journal d'activité | Repérer ce qui demande une action |
| Mon réseau | Canaux & groupes, Organisation | Synchroniser, filtrer les types/rôles, relier localement ses entités |
| Découverte & contenus | Liens & sources, Médiathèque | Identifier → autoriser → importer → vérifier |
| Diffusion | Studio, File & historique, Calendrier, Règles | Préparer → valider → programmer → exécuter |
| Partenariats | Répertoire, Échanges, Rédaction | Documenter une relation → préparer un accord → programmer → vérifier |
| Analyses | Statistiques, Surveillance | Lire les observations disponibles et leurs limites |
| Compte & paramètres, séparé | Connexion & préférences | API → numéro → code → 2FA si nécessaire → synchronisation |

Les routes portent des noms stables. Les pages existantes sont réutilisées. Les onglets de publication restent le même composant, piloté par les sous-routes Studio / File / Calendrier pour éviter une deuxième barre d'onglets redondante.

## Périmètre technique

- Migration SQLite additive et sauvegarde avant migration, sans perte des notes, preuves, médias, tâches ou relations existantes.
- Classification des entités Telegram, droits conservateurs, filtres type/rôle/administration/visibilité et contrôle d'envoi actualisé.
- Organisation hiérarchique locale des entités, sans créer d'invitations ni modifier Telegram implicitement. Les invitations et demandes d'adhésion restent une étape ultérieure nécessitant leurs propres contrôles d'administration et confirmations.
- Découverte bornée : ajout explicite d'un identifiant/lien accessible, filtrage du catalogue local et sources avec preuves. Pas de moteur universel, pas d'adhésion automatique, pas d'extraction de membres.
- Aide centralisée : présentation de chaque page et descriptions des contrôles. Inspection locale par survol, sans déclencher les actions inspectées, quittable par Échap et à la navigation.
- Conservation des validations de publication, du masque des médias sensibles, des refus de contenu protégé et de l'état `unknown`.

Les recommandations de partenaires, invitations administrées, découverte distante étendue, nouvelles automatisations et IA externe restent explicitement hors de cette première refonte. Aucun bouton factice n'est créé pour ces fonctions.

## Diagnostic de connexion associé

Le `TypeError` reproduit sans compte se situe dans `telethon/tl/tlobject.py:serialize_bytes` : le numéro vide est converti en `None` par `send_code_request`, puis `SendCodeRequest` tente de sérialiser ce numéro. Le défaut de TelePilot est l'absence de validation et l'affichage prématuré du bouton de demande de code.

Le seul appel de configuration et le clic Qt de configuration ont également été exécutés avec une session temporaire et des identifiants fictifs : ils n'ont pas produit de `TypeError`. Le journal ancien ne contenait aucune traceback ; le cas historique exact de l'utilisateur ne peut donc pas être affirmé sans cette trace ou confirmation du bouton utilisé. La nouvelle journalisation conserve les frames et les types d'exception, sans messages bruts, notes ni variables locales sensibles.

Références : [types de discussions Telethon](https://docs.telethon.dev/en/stable/concepts/chats-vs-channels.html), [authentification Telegram](https://core.telegram.org/api/auth), [aide Qt](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QWhatsThis.html). Les signatures et le code effectif de la version installée sont vérifiés par les tests.
