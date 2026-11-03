# Vérifier la nouvelle importation

Cette recette sur un compte Telegram réel est laissée à l'utilisateur. Le développement a vérifié les flux avec des données fictives locales ; aucune connexion Telegram réelle n'a été utilisée.

## Parcours rapide

1. Fermer l'ancienne fenêtre TelePilot, rouvrir **TelePilot.command** du Bureau et connecter le compte si nécessaire.
2. Synchroniser **Mon réseau → Canaux & groupes**. Pour un canal que vous avez le droit de récupérer, documenter une fois la source dans **Découverte & contenus → Liens & sources**. Un canal public ou administré ne donne pas à lui seul les droits sur chaque média.
3. Sélectionner le canal, cliquer **Télécharger les médias**, garder **Tous les médias accessibles et autorisés**, puis cliquer **Télécharger**. L'import doit commencer sans activer les publications. Les compteurs restent visibles en changeant de page.
4. Refaire avec **Photos**, puis **Vidéos**. Dans la médiathèque, vérifier les miniatures, la source, la date, la taille, l'ouverture du dossier et les médias apparus avant la fin du balayage.
5. Mettre en pause, reprendre et annuler une importation. Les fichiers déjà terminés doivent rester dans la galerie. Fermer puis rouvrir l'application avec une tâche non terminée : elle doit reprendre au prochain message.
6. Réimporter la même source : les médias déjà référencés ne doivent pas être dupliqués. Essayer une source sans autorisation documentée, puis un canal qui protège ses contenus : le téléchargement doit être refusé avec une raison claire.
7. Sur une source autorisée, activer **Importer automatiquement les nouveaux médias**. Les anciens messages présents à cet instant ne doivent pas être repris. Publier un nouveau média autorisé, attendre au plus cinq minutes avec TelePilot ouvert, puis vérifier son apparition. Le bouton **Arrêter l'importation automatique** doit stopper les nouveaux téléchargements.

La démonstration contient une source fictive **Maison Atlas** avec deux photos et une courte vidéo locale. Elle permet d'essayer le parcours sans compte ni réseau : ouvrir **Liens & sources**, sélectionner Maison Atlas, puis **Télécharger les médias**.

## Limites connues

- Le nombre total de médias n'est pas connu avant le balayage pour un canal réel ; la barre reste indéterminée sans limite avancée. Les compteurs trouvés, téléchargés, ignorés et erreurs sont réels.
- L'import automatique vérifie les sources toutes les cinq minutes lorsque l'application est ouverte et connectée. Ce n'est pas un service macOS en arrière-plan.
- Un fichier interrompu pendant son transfert est repris depuis le début ; le curseur de message et les doublons évitent de recommencer tout l'historique.
- Les miniatures vidéo utilisent Quick Look ou, si déjà installé, `ffmpeg` ; sinon un repère vidéo apparaît. Les aperçus sensibles restent masqués selon la préférence.
- Un média téléchargé reste à revoir avant toute publication. Le téléchargement n'active jamais les publications.
