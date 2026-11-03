# Périmètre courant (0.3, téléchargement direct)

La version 0.3 conserve la refonte de navigation et de connexion de la version 0.2, puis simplifie l'importation de médias. Voir [l'audit](AUDIT_REFONTE.md), [le compte rendu](COMPTE_RENDU_REFONTE.md) et [la recette d'importation](VALIDATION_IMPORT.md).

Le dossier était vide au démarrage. Le cahier des charges fourni s'interrompt dans la section « Assistant IA », après « Suggestions et ». Cette version construit les flux locaux et les interfaces réelles ; elle ne prétend pas avoir livré ou validé l'ensemble du produit commercial décrit.

| Domaine | Livré | À compléter |
|---|---|---|
| Desktop | Qt Widgets, six espaces et sous-pages, aide de page et inspection locale, commandes asynchrones, lancement macOS, démonstration isolée | Bundle `.app` autonome, signature, notarisation, mise à jour distribuée, accessibilité approfondie |
| Connexion | API ID/hash, trousseau natif facultatif et coché par défaut, téléphone, code, 2FA, restauration automatique au lancement, déconnexion, isolation d'un compte par espace | Recette avec un compte réel, parcours multi-comptes dans une même fenêtre |
| Réseau | Canaux, groupes, supergroupes, types/rôles/visibilité, associations locales hiérarchiques, droits et demandes d'adhésion exposés, notes, dernières publications | Gestion effective des invitations et demandes d'adhésion, avatars, descriptions enrichies, contrôles d'architecture avancés |
| Sources | Permissions documentées, restrictions Telegram, activation du suivi, mots-clés | Pièces jointes aux preuves de consentement, historique détaillé des versions de licences |
| Import | Tous/Photos/Vidéos sans période ni limite par défaut, options avancées repliées, démarrage direct sans activer les publications, compteurs visibles, galerie progressive, doublons, pause/reprise, arrêt et contrôle d'espace disque, import automatique des nouveaux messages par sondage | Progression en octets, reprise d'un fichier au milieu du transfert, nombre total de médias avant balayage, événements temps réel, choix visuel d'albums complets |
| Médiathèque | Grille, recherche, filtres, tris, multi-sélection, favoris, légendes, revue et retrait, aperçus privés | Pagination au-delà de 200 éléments affichés, miniatures vidéo, prévisualisation vidéo intégrée et gestion éditoriale avancée |
| Publication | Brouillons, duplication, texte/médias/albums, crédit, programmation ponctuelle, calendrier, file et historique | Édition en place des tâches programmées, récurrences par jours/créneaux, remplissage automatique depuis une sélection approuvée |
| Fiabilité | SQLite/WAL, contrôle des droits à l'envoi, récupération, `unknown`, délais Telegram, intervalle minimum, verrou d'instance | Tests d'interruption avec Telegram réel, rapprochement automatique des envois ambigus lorsque prouvable, contrôles de gros volumes |
| Surveillance | Observation manuelle/périodique bornée, nouveautés, modifications textuelles, mots-clés et erreurs | Événements Telegram temps réel, suivi fiable des suppressions, notifications système et politique de rétention configurable |
| Statistiques | Vues/réactions/partages observés, graphe Qt, snapshots d'abonnés stockés | API statistiques officielles selon éligibilité, périodes/comparaisons avancées, graphes d'évolution d'abonnés, attribution publicitaire |
| Partenaires | Répertoire manuel, canal associé, audience déclarée, consentement, notes, conditions, retrait de consentement | Modification complète des fiches, import CSV contrôlé, historique des contacts, recommandations expliquées |
| Échanges | Deux canaux, deux textes, date/durée/conditions, états manuels, validation d'accord, tâche locale, vérification limitée du partenaire | Réception automatique des propositions, négociation structurée, surveillance de la durée de maintien, rappels et suivi des litiges |
| IA | `AIProvider` abstrait, fournisseur désactivé, modèles de réponse locaux | Fournisseur choisi par l'utilisateur, aperçu/consentement par requête, contrôle des usages autorisés des données, résumé et analyse semi-automatiques |
| Contenus sensibles | Masque opaque par défaut, revue humaine, consentement/majorité attestés, provenance, retrait et historique | Gestion des dossiers de demande de suppression et workflow juridique complet avant commercialisation |

## Limites opérationnelles explicites

- Les statistiques et vérifications portent sur ce que l'API expose au compte. Un message absent des derniers résultats n'est pas déclaré supprimé. Une publication retrouvée ne prouve pas sa durée de maintien.
- Par défaut, l'import parcourt tous les messages accessibles de la source. Un plafond avancé peut couper un album ; les identifiants de groupe restent enregistrés et la sélection des médias à republier est manuelle.
- L'import automatique sonde les sources toutes les cinq minutes quand TelePilot est ouvert et connecté. Il démarre au dernier message présent lors de son activation ; aucun ancien contenu n'est téléchargé automatiquement. Les fichiers interrompus reprennent au message, pas à l'octet.
- La recherche de doublons Telegram évite de télécharger de nouveau un message déjà importé. Un même fichier publié dans deux messages différents peut nécessiter deux téléchargements avant détection par SHA-256.
- Les annulations ne rappellent pas une requête déjà transmise à Telegram.
- Les miniatures sensibles sont cachées par un masque opaque plutôt que par un flou réversible.
- La planification n'est pas un service système : l'application doit rester ouverte et le Mac éveillé.
- Les copies de sauvegarde SQLite ne comprennent ni les médias, ni les éléments du trousseau.
- Aucun fournisseur IA n'est connecté, aucun message de prospection n'est envoyé et aucun contrat n'est accepté automatiquement.

## Prochaines étapes d'acceptation

1. Recette manuelle sur un canal privé : connexion, permissions, import autorisé, photo/vidéo/album, délais et résultat incertain.
2. Compléter les fonctions éditoriales (édition des brouillons, regroupement des albums, récurrences) et les fiches partenaires.
3. Ajouter les demandes entrantes consenties, la revue et la rédaction assistée après sélection d'un fournisseur et contrôle des conditions d'utilisation des données.
4. Enrichir les statistiques, tester les volumes réels, documenter la rétention et les mises à jour.
5. Préparer la distribution macOS et vérifier les exigences applicables à la commercialisation : licences des dépendances, conditions Telegram, notamment les messages sponsorisés officiels, confidentialité et traitement des contenus/demandes de retrait.

Les conditions de l'API Telegram incluent des règles sur les données utilisées avec l'IA et les messages sponsorisés. Le produit ne doit pas être présenté comme prêt à être commercialisé avant examen de ces exigences et recette des fonctions réelles. Référence : [conditions officielles](https://core.telegram.org/api/terms).

