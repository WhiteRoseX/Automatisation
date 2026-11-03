# Architecture

## Couches

```text
Qt Widgets (ui/)
    │ commandes, résultats et instantanés par signaux Qt
    ▼
ApplicationService (service.py)
    ├── MediaLibrary     : stockage, provenance, droits et retrait
    ├── TaskQueue        : validation, persistance et transitions
    ├── Engine           : un seul exécuteur de tâches
    ├── Importer         : curseurs persistants et téléchargement autorisé
    ├── Partners         : accords et tâches publicitaires
    ├── Monitor          : observations bornées et vérifications
    └── AIProvider       : contrat optionnel, aucune intégration externe active
    │
    ├── Database (sqlite3, WAL, transactions, version de schéma)
    └── TelegramGateway
           ├── TelethonGateway (telegram/client.py)
           └── DemoGateway     (telegram/demo.py)
```

Le cœur `core/` n'importe ni Qt ni Telethon. `service.py` compose les fonctions métier. Les éléments graphiques n'écrivent pas de SQL et ne connaissent pas les types Telethon. `TelegramGateway` définit le contrat de publication ; l'adaptateur ajoute les opérations de connexion, d'importation et de résolution de canaux.

Depuis 0.2, `ui/navigation.py` centralise les espaces et routes nommées ; `ui/help_registry.py` centralise les textes d'aide. `ui/help.py` réalise l'inspection locale avec un filtre d'événements Qt et les métadonnées accessibles. La navigation arrête l'inspection, y compris lorsque deux routes partagent la même vue de publication. `core/network.py` conserve uniquement les associations locales et refuse les cycles.

Le nom historique `Channel` / `channels` est conservé pour éviter de casser les références de provenance et de tâches. Le schéma 2 ajoute les champs `entity_type`, `role`, `visibility`, `can_invite` et `join_request`. Le schéma 3 ajoute la vérification de téléchargement, le curseur d'importation automatique et la date du message dans la provenance. Chaque migration crée une sauvegarde cohérente avant modification. `broadcast`, `supergroup` et `group` sont distingués ; les messages privés ne sont jamais insérés comme entités du réseau.

## Exécution

Le thread principal est réservé à Qt. Un thread standard possède une boucle `asyncio`, le client Telethon, les commandes de l'application et le moteur. Les copies/hashes de gros fichiers, le trousseau et les décodages d'image passent par un exécuteur borné à deux workers. Les connexions SQLite sont locales à chaque opération, avec clés étrangères, délai de verrouillage et fermeture explicite.

Le moteur traite une seule tâche à la fois. Les imports autorisés sont exécutés même lorsque les publications sont suspendues ; l'activation explicite ne contrôle que l'envoi. Les commandes restent disponibles pendant les attentes réseau. L'arrêt attend la terminaison des copies en cours avant de fermer le processus. Le verrou de processus évite une récupération concurrente d'un même espace.

La surveillance périodique est une unique coroutine avec un intervalle de cinq minutes. L'observation statistique et l'import des nouveaux médias sont des choix persistants distincts par source. L'import automatique part du dernier identifiant présent à son activation et ne reprend pas l'historique. Son exécution dépend d'une session active, de l'accès et des permissions de source. Une erreur ne déclenche jamais une publication.

## Envois et incertitude

Les tâches possèdent les huit états demandés : `draft`, `pending`, `scheduled`, `running`, `completed`, `failed`, `cancelled`, `unknown`. La pause d'un import est un attribut séparé, pas un état supplémentaire.

1. Une publication validée reçoit son contenu final, les médias référencés, un instant UTC et un identifiant aléatoire de requête persistant.
2. La prise de tâche est atomique (`BEGIN IMMEDIATE`).
3. Le moteur vérifie les droits du média, ceux de la source et le droit actuel de publier dans le canal.
4. Les droits des médias sont revérifiés après le contrôle réseau.
5. Un succès enregistre les identifiants des messages. Un refus RPC explicite échoue ; un délai Telegram reporte la tâche et pose une suspension globale persistante.
6. Si une erreur survient après le début d'un envoi sans confirmation, la tâche passe à `unknown`. Elle n'est jamais reprise automatiquement.
7. Au redémarrage, toute publication `running` devient `unknown`, même si l'arrêt a pu se produire avant son envoi. Ce choix privilégie l'absence de doublons au détriment de la disponibilité automatique.

Pour le texte, l'adaptateur envoie un `random_id` persistant via MTProto. Les albums et fichiers utilisent `send_file` ; l'application ne prétend pas garantir un envoi « exactement une fois » pour ces opérations. Un album peut avoir été partiellement publié lors d'une interruption. La résolution de `unknown` exige une vérification humaine et la présence des identifiants déclarés dans les 100 derniers messages du canal. L'application ne déduit jamais « non envoyé » d'une absence dans cette fenêtre.

Les tentatives automatiques avant envoi sont bornées. Les tâches inconnues, échouées ou terminées peuvent être chargées comme nouvelles propositions dans le studio ; cette action n'envoie rien. Réutiliser un média déjà prévu/publié exige une confirmation explicite de répétition.

Les tâches publicitaires ont un identifiant stable dérivé de l'échange : un arrêt entre création de la tâche et rattachement de l'accord ne produit pas de deuxième tâche au prochain essai.

## Médias et droits

Les fichiers sont copiés dans un fichier temporaire privé en calculant SHA-256, synchronisés puis renommés. L'empreinte porte sur les octets réellement stockés. Le nom original est une métadonnée. Le registre de provenance porte les identifiants de source, message, média Telegram et groupe d'album.

Un doublon ne promeut pas les droits du fichier existant et ne réactive pas un contenu retiré. Pour publier, le média doit être approuvé, non retiré, documenté, présent sur disque et issu de sources encore autorisées. La revue humaine atteste les droits, le consentement et la majorité si nécessaire ; elle ne constitue pas une vérification automatique infaillible de la légalité.

L'import Telegram conserve un curseur et des compteurs après chaque message. En cas d'arrêt après stockage mais avant sauvegarde du curseur, la provenance permet d'éviter un nouveau téléchargement du même message. Un fichier interrompu pendant son téléchargement est téléchargé de nouveau au prochain essai ; la reprise par octet n'est pas implémentée. La pause prend effet après le fichier en cours ; l'annulation vérifie l'état avant l'enregistrement. Un seuil d'espace libre est contrôlé avant chaque copie.

La protection du canal est vérifiée avant le téléchargement et celle du message à son chargement. Les contenus protégés ne sont pas copiés. Les médias importés restent non vérifiés jusqu'à leur revue individuelle.

## Secrets et données

API hash : mémoire ou trousseau macOS. Mot de passe 2FA et code : mémoire transitoire uniquement, champs effacés à la soumission. Session : fichier SQLite Telethon privé. Logs : uniquement cycle de vie sans payload ni exception brute de Telegram. Les erreurs présentées à l'utilisateur sont des messages contrôlés ou des noms de classes d'erreurs.

Les réponses provenant de Telegram sont présentées en texte brut dans Qt, sans interprétation de HTML. Les médias ne sont pas envoyés à des services d'analyse. Aucun envoi de message privé, contrat ni engagement financier n'est automatisé.

`diagnostics.py` consigne toutes les frames de la traceback et les classes des exceptions chaînées, sans variables locales, lignes de code, messages bruts ni notes d'exception. Les valeurs sensibles pouvant apparaître dans ces éléments ne sont pas sérialisées dans les journaux. Les tests injectent de faux secrets dans les différents emplacements pour vérifier leur absence.

