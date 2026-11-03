# Recette avec un compte de test

Ces étapes sont manuelles et n'ont pas été réalisées sur un compte réel pendant le développement. Elles nécessitent les identifiants API de l'utilisateur, un canal privé administré et quelques contenus de test dont les droits sont établis.

## Authentification

- Ouvrir le mode réel. Saisir API ID/hash, configurer, demander un code et se connecter.
- Vérifier un code invalide et expiré ; demander un nouveau code si nécessaire.
- Vérifier le parcours 2FA. Confirmer que les champs sont effacés après soumission.
- Avec l'option trousseau cochée, fermer et rouvrir : le compte doit se reconnecter automatiquement, sans clic, code ni mot de passe 2FA.
- Révoquer la session depuis Telegram, constater l'erreur puis reconnecter.
- Confirmer que l'identité correspond au compte attendu. Un autre compte doit être refusé pour le même espace.

## Import et droits

- Synchroniser les canaux, documenter une source de test et importer une plage réduite.
- Importer de nouveau la même plage ; vérifier l'absence de nouvelles lignes média/provenance inutiles.
- Comparer une photo, une vidéo et un album à la source. Vérifier légendes et groupement dans la base.
- Sur un canal protégeant ses contenus, vérifier le refus d'importation sans contournement.
- Suspendre puis reprendre une importation. Annuler une autre tâche et vérifier l'arrêt au prochain checkpoint.
- Essayer de programmer un média non vérifié : refus attendu. Documenter ses droits et effectuer la revue, puis réessayer.

## Publication

- Prévisualiser un texte et ses liens ; confirmer la publication dans le canal de test et activer la file.
- Publier successivement une photo, une vidéo et un album court. Vérifier le nombre de messages et les légendes.
- Programmer une publication, fermer l'application, rouvrir et vérifier sa présence avant d'activer la file.
- Retirer les droits d'un média programmé : la tâche doit être annulée ou bloquée avant l'envoi.
- Retirer les droits administrateur du compte avant une tâche : aucun envoi ne doit aboutir.
- Pour tester une interruption, utiliser uniquement le canal de test. Une tâche interrompue pendant l'envoi doit rester `unknown`. Vérifier réellement le canal avant de la résoudre ou de préparer une nouvelle publication.
- Ne pas provoquer volontairement du spam pour déclencher `FloodWait` : cette condition est testée par simulation automatique.

## Partenariats et suivi

- Ajouter un partenaire fictif relié à un second canal de test, créer un échange et documenter les textes/date/durée.
- Avant « Accord conclu », la programmation doit être refusée.
- Après validation, créer une seule tâche dans son propre canal. Refaire l'action ne doit pas créer de doublon.
- Ajouter et autoriser le suivi du canal partenaire, publier le texte convenu et lancer la vérification.
- Vérifier la formulation des incertitudes : observation du texte/lien, sans prétendre prouver la durée.

## Confidentialité et fermeture

- Vérifier le masque des médias sensibles au lancement, puis la confirmation lors de leur consultation.
- Inspecter les logs de l'espace : aucun numéro, mot de passe, API hash, contenu de message ou session ne doit apparaître.
- Fermer pendant une copie/importation et vérifier l'arrêt propre ; reprendre l'espace ensuite.
- Sauvegarder la base et vérifier sa lecture hors ligne. Ne jamais remplacer la base active pendant l'exécution.

