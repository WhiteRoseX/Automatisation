# Importation simplifiée (0.3.2)

## Parcours

1. Connecter Telegram, synchroniser les canaux et groupes.
2. Depuis **Mon réseau** sélectionner une ligne et **Télécharger les médias**, ou depuis **Médiathèque** choisir directement le canal.
3. Choisir Photos / Vidéos / Tout.
4. Choisir **Tout télécharger** pour parcourir l'historique accessible ou **Choisir les médias** pour sélectionner des publications des 200 derniers messages.
5. Pour un canal tiers, confirmer les droits de téléchargement; les protections Telegram bloquent le traitement.
6. Voir la progression dans la barre supérieure et la médiathèque. La vérification des droits de republication reste indépendante.

## Notes

- La sélection des médias distants est actuellement une liste avec type, date et légende (pas encore une grille avec miniatures).
- L'option *Tout télécharger* n'est plus limitée implicitement à 100 publications. Elle traite les messages par lots de 100 et peut être suspendue ou annulée.
- Les messages non trouvés dans une sélection sont sautés et comptabilisés. L'importation conserve son curseur.
- Les médias sont stockés localement et marqués non vérifiés pour la republication.
- Tests automatisés du noyau ajoutés : propriétaire, autorisation tierce, contenu protégé, sélection et historique de 230 messages.
- L'interface PySide6 et les appels Telegram réels doivent être validés sur un Mac connecté : non disponibles dans l'environnement de tests actuel.
