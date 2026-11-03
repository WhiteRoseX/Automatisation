"""Application facade. UI commands pass through this layer; Qt stays outside."""

import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from .core.database import Database
from .core.engine import Engine
from .core.importer import Importer
from .core.media import MediaLibrary
from .core.models import ALLOWED_RIGHTS, DomainError, Rights, now
from .core.monitor import Monitor
from .core.network import Network, public_reference
from .core.partners import Partners
from .core.tasks import TaskQueue
from .diagnostics import log_exception
from .security import Keychain


class ApplicationService:
    def __init__(self, paths, gateway, demo):
        self.paths, self.gateway, self.demo = paths, gateway, demo
        self.db = Database(paths.database)
        self.library = MediaLibrary(self.db, paths.media)
        self.queue = TaskQueue(self.db, self.library)
        self.importer = Importer(self.db, self.library, self.queue, gateway)
        self.partners = Partners(self.db, self.queue)
        self.monitor = Monitor(self.db, gateway)
        self.network = Network(self.db)
        self.engine = Engine(self.db, self.queue, gateway, self.importer)
        self.auth_lock = asyncio.Lock()
        self.engine.auth_lock = self.auth_lock
        self.queue.recover()

    def upsert_channel(self, channel):
        data = asdict(channel)
        self.db.execute(
            """INSERT INTO channels(id,title,username,description,can_post,protected,subscribers,synced_at,entity_type,role,visibility,can_invite,join_request)
            VALUES (:id,:title,:username,:description,:can_post,:protected,:subscribers,:synced_at,:entity_type,:role,:visibility,:can_invite,:join_request)
            ON CONFLICT(id) DO UPDATE SET title=excluded.title,username=excluded.username,description=excluded.description,
            can_post=excluded.can_post,protected=excluded.protected,subscribers=excluded.subscribers,synced_at=excluded.synced_at,
            entity_type=excluded.entity_type,role=excluded.role,visibility=excluded.visibility,can_invite=excluded.can_invite,join_request=excluded.join_request""",
            dict(data, synced_at=now()),
        )
        self.db.execute(
            "INSERT INTO metrics(channel_id,captured_at,subscribers) VALUES (?,?,?)",
            (channel.id, now(), channel.subscribers),
        )

    async def sync_channels(self):
        channels = await self.gateway.channels()
        # Stale admin rights must not remain publishable when a dialog disappears.
        self.db.execute("UPDATE channels SET can_post=0,can_invite=0,role='unknown'")
        for channel in channels:
            self.upsert_channel(channel)
        self.db.event(
            "sync",
            "Réseau synchronisé",
            f"{len(channels)} canaux et groupes accessibles",
        )
        return f"{len(channels)} canaux et groupes synchronisés"

    @staticmethod
    def source_may_download(source, channel):
        if not source or not channel or channel["protected"]:
            return False
        evidence = (source.get("evidence") or "").strip()
        return bool(
            (source["rights"] in ALLOWED_RIGHTS and evidence)
            or evidence.startswith("download-confirmed:")
        )

    async def prepare_download_source(self, channel_id, permission_declared=False):
        channel = self.db.one("SELECT * FROM channels WHERE id=?", (channel_id,))
        if not channel or channel["role"] == "unknown":
            raise DomainError("Canal introuvable. Synchronisez d'abord votre réseau.")
        if channel["protected"]:
            raise DomainError(
                "Téléchargement impossible : contenu protégé par Telegram."
            )
        current = self.db.one("SELECT * FROM sources WHERE channel_id=?", (channel_id,))
        owner = channel["role"] == "owner"
        authorized = self.source_may_download(current, channel)
        if not owner and not (authorized or permission_declared):
            raise DomainError(
                "Confirmez votre droit de télécharger les médias de ce canal."
            )
        # Check the actual Telegram capability before writing permission metadata.
        await self.gateway.check_source(channel_id)
        if not current:
            rights = "own" if owner else "unverified"
            evidence = (
                "Canal possédé par le compte connecté"
                if owner
                else "download-confirmed: confirmation utilisateur de permission de téléchargement"
            )
            self.db.execute(
                "INSERT INTO sources(channel_id,title,rights,evidence) VALUES (?,?,?,?)",
                (channel_id, channel["title"], rights, evidence),
            )
        elif owner and current["rights"] == "unverified":
            self.db.execute(
                "UPDATE sources SET rights='own',evidence=? WHERE id=?",
                ("Canal possédé par le compte connecté", current["id"]),
            )
        elif not authorized and permission_declared:
            self.db.execute(
                "UPDATE sources SET evidence=? WHERE id=?",
                (
                    "download-confirmed: confirmation utilisateur de permission de téléchargement",
                    current["id"],
                ),
            )
        source = self.db.one("SELECT * FROM sources WHERE channel_id=?", (channel_id,))
        self.db.execute(
            "UPDATE sources SET download_checked_at=?,download_error='' WHERE id=?",
            (now(), source["id"]),
        )
        return source

    def source_status(self, source, channels):
        channel = channels.get(source["channel_id"])
        # A stale preflight is not a reason to force the user into another
        # screen: command("import_telegram") verifies access immediately.
        can_attempt = bool(
            self.gateway.connected
            and channel
            and channel["role"] != "unknown"
            and self.source_may_download(source, channel)
        )
        if not self.gateway.connected:
            reason = "Connectez votre compte Telegram."
        elif not channel:
            reason = "Source inaccessible. Synchronisez le réseau."
        elif channel["role"] == "unknown":
            reason = "Source non synchronisée. Actualisez le réseau."
        elif channel["protected"]:
            reason = "Ce canal protège ses contenus : téléchargement interdit."
        elif not self.source_may_download(source, channel):
            reason = "Confirmez les droits de téléchargement pour cette source."
        elif source["download_error"]:
            reason = source["download_error"]
        elif (
            not source["download_checked_at"]
            or now() - source["download_checked_at"] > 3600
        ):
            reason = "L'accès sera contrôlé automatiquement au téléchargement."
        else:
            reason = ""
        known = getattr(self.gateway, "known_media_count", lambda _id: None)(
            source["channel_id"]
        )
        return dict(
            source,
            downloadable=not bool(reason),
            can_attempt_download=can_attempt,
            download_reason=reason,
            available_media=known,
        )

    async def verify_source(self, source_id):
        source = self.db.one("SELECT * FROM sources WHERE id=?", (source_id,))
        channel = (
            self.db.one("SELECT * FROM channels WHERE id=?", (source["channel_id"],))
            if source
            else None
        )
        if not self.source_may_download(source, channel):
            raise DomainError("La source n'est pas autorisée pour ce téléchargement.")
        if not channel or channel["role"] == "unknown" or channel["protected"]:
            raise DomainError("Ce canal est absent ou protège ses contenus.")
        try:
            await self.gateway.check_source(source["channel_id"])
        except Exception as exc:
            reason = (
                str(exc)
                if isinstance(exc, DomainError)
                else "Accès Telegram indisponible. Vérifiez la session ou le réseau."
            )
            self.db.execute(
                "UPDATE sources SET download_checked_at=0,download_error=? WHERE id=?",
                (reason, source_id),
            )
            raise DomainError(reason) from None
        self.db.execute(
            "UPDATE sources SET download_checked_at=?,download_error='' WHERE id=?",
            (now(), source_id),
        )
        return source

    async def poll_auto_imports(self):
        if not self.gateway.connected:
            return
        for source in self.db.rows("SELECT * FROM sources WHERE auto_import=1"):
            active = any(
                json.loads(task["payload"]).get("source_id") == source["id"]
                for task in self.db.rows(
                    "SELECT payload FROM tasks WHERE kind='import' AND state IN ('pending','scheduled','running')"
                )
            )
            if active:
                continue
            try:
                await self.verify_source(source["id"])
                latest = await self.gateway.latest_message_id(source["channel_id"])
                self.db.execute(
                    "UPDATE sources SET auto_checked_at=? WHERE id=?",
                    (now(), source["id"]),
                )
                current = self.db.one(
                    "SELECT auto_import,auto_cursor FROM sources WHERE id=?",
                    (source["id"],),
                )
                if (
                    current
                    and current["auto_import"]
                    and latest > current["auto_cursor"]
                ):
                    self.importer.create(
                        source["id"], automatic=True, cursor=current["auto_cursor"]
                    )
            except Exception as exc:
                log_exception(exc, "auto_import")
                reason = (
                    str(exc)
                    if isinstance(exc, DomainError)
                    else "Surveillance indisponible. Vérifiez la connexion."
                )
                self.db.execute(
                    "UPDATE sources SET download_checked_at=0,download_error=?,auto_checked_at=? WHERE id=?",
                    (reason, now(), source["id"]),
                )

    def snapshot(self):
        tables = {
            name: self.db.rows(f"SELECT * FROM {name} ORDER BY {order}")
            for name, order in (
                ("channels", "title"),
                ("sources", "title"),
                ("media", "created_at DESC"),
                ("tasks", "created_at DESC"),
                ("partners", "name"),
                ("exchanges", "due_at"),
            )
        }
        tables["events"] = self.db.rows(
            "SELECT * FROM events ORDER BY id DESC LIMIT 100"
        )
        tables["observations"] = self.db.rows(
            "SELECT * FROM observations ORDER BY published_at DESC LIMIT 200"
        )
        tables["metrics"] = self.db.rows(
            "SELECT * FROM metrics ORDER BY captured_at DESC LIMIT 500"
        )
        tables["task_media"] = self.db.rows("SELECT * FROM task_media")
        tables["provenance"] = self.db.rows("SELECT * FROM provenance")
        tables["network_links"] = self.db.rows("SELECT * FROM network_links")
        channels = {row["id"]: row for row in tables["channels"]}
        tables["sources"] = [
            self.source_status(row, channels) for row in tables["sources"]
        ]
        return dict(
            tables,
            identity=self.gateway.identity,
            connected=self.gateway.connected,
            auth_state=getattr(
                self.gateway,
                "auth_state",
                "connected" if self.gateway.connected else "credentials",
            ),
            code_delivery=getattr(self.gateway, "code_delivery", ""),
            engine=self.engine.enabled,
            demo=self.demo,
            root=str(self.paths.root),
            blur=self.db.setting("blur", "1") == "1",
            interval=self.db.setting("send_interval", "60"),
            api_id=self.db.setting("api_id"),
            auto_watch=self.db.setting("auto_watch", "0") == "1",
        )

    async def command(self, name, **args):
        if name == "snapshot":
            return self.snapshot()
        if name == "create_community":
            result = await self.gateway.create_community(
                args.get("title", ""), args.get("about", ""), args.get("kind", "channel")
            )
            self.upsert_channel(result)
            self.db.event("network", "Nouvelle communauté", result.title, result.id)
            return {"id": result.id, "title": result.title}
        if name == "channel_avatar":
            channel_id = int(args["channel_id"])
            if not self.db.one("SELECT id FROM channels WHERE id=?", (channel_id,)):
                raise DomainError("Canal inconnu.")
            return await self.gateway.channel_avatar(
                channel_id, self.paths.media / "avatars"
            )
        if name == "partner_messages":
            partner = self.db.one("SELECT * FROM partners WHERE id=?", (int(args["partner_id"]),))
            if not partner:
                raise DomainError("Partenaire introuvable.")
            return await self.gateway.partner_messages(partner["handle"])
        if name == "partner_reply":
            partner = self.db.one("SELECT * FROM partners WHERE id=?", (int(args["partner_id"]),))
            if not partner or partner["opted_out"]:
                raise DomainError("Ce partenaire n'est pas disponible pour la messagerie.")
            message_id = await self.gateway.reply_to_partner(partner["handle"], args.get("text", ""))
            self.db.execute("UPDATE partners SET last_contact=? WHERE id=?", (now(), partner["id"]))
            self.db.event("partner", "Réponse envoyée", partner["name"])
            return {"message_id": message_id}
        if name == "sync_channels":
            return await self.sync_channels()
        if name == "engine":
            if args["enabled"] and not self.gateway.connected:
                raise DomainError(
                    "Connectez votre compte Telegram avant d'activer la file."
                )
            if args["enabled"] and self.auth_lock.locked():
                raise DomainError(
                    "Attendez la fin de la connexion avant d'activer la file."
                )
            self.engine.enabled = args["enabled"]
            return (
                "File activée"
                if self.engine.enabled
                else "File suspendue après l'opération en cours"
            )
        if name == "import_local":
            count = 0
            for path in args.pop("paths"):
                await asyncio.to_thread(self.library.import_file, path, **args)
                count += 1
            return f"{count} fichiers traités · doublons fusionnés"
        if name == "approve_media":
            return self.library.approve(**args)
        if name == "withdraw":
            return self.library.withdraw(**args)
        if name == "favorite":
            self.db.execute(
                "UPDATE media SET favorite=1-favorite WHERE id=?", (args["media_id"],)
            )
            return
        if name == "publish":
            return self.queue.publication(**args)
        if name == "cancel":
            return self.queue.cancel(**args)
        if name == "pause":
            return self.queue.pause(**args)
        if name == "resolve":
            task = self.db.one(
                "SELECT * FROM tasks WHERE id=? AND state='unknown'", (args["task_id"],)
            )
            if not task:
                raise DomainError("Cette tâche n'est pas en état incertain.")
            p = json.loads(task["payload"])
            messages = await self.gateway.recent(p["channel_id"], 100)
            found = {m["id"]: m for m in messages}
            if any(mid not in found for mid in args["message_ids"]):
                raise DomainError(
                    "Identifiants absents des 100 dernières publications. Vérifiez le canal dans Telegram."
                )
            return self.queue.resolve(**args)
        if name == "source":
            if args["rights"] not in Rights:
                raise DomainError("Droits invalides.")
            channel = self.db.one(
                "SELECT * FROM channels WHERE id=?", (args["channel_id"],)
            )
            if not channel:
                raise DomainError("Canal introuvable.")
            if args["rights"] in ALLOWED_RIGHTS and not args["evidence"].strip():
                raise DomainError("Documentez l'autorisation de la source.")
            rights = "protected" if channel["protected"] else args["rights"]
            self.db.execute(
                """INSERT INTO sources(channel_id,title,rights,evidence,watch,keywords) VALUES (?,?,?,?,?,?)
                ON CONFLICT(channel_id) DO UPDATE SET rights=excluded.rights,evidence=excluded.evidence,watch=excluded.watch,keywords=excluded.keywords""",
                (
                    channel["id"],
                    channel["title"],
                    rights,
                    args["evidence"],
                    int(args["watch"]),
                    args["keywords"],
                ),
            )
            source_id = self.db.one(
                "SELECT id FROM sources WHERE channel_id=?", (channel["id"],)
            )["id"]
            self.db.execute(
                "UPDATE sources SET download_checked_at=0,download_error='',auto_import=CASE WHEN ? THEN auto_import ELSE 0 END WHERE id=?",
                (
                    int(rights in ALLOWED_RIGHTS and bool(args["evidence"].strip())),
                    source_id,
                ),
            )
            self.db.event(
                "rights", "Autorisation de source mise à jour", channel["title"]
            )
            if rights in ALLOWED_RIGHTS and args["evidence"].strip():
                await self.verify_source(source_id)
            return "Autorisation enregistrée."
        if name == "channel_notes":
            self.db.execute(
                "UPDATE channels SET category=?,notes=? WHERE id=?",
                (args["category"], args["notes"], args["channel_id"]),
            )
            return
        if name == "resolve_channel":
            channel = await self.gateway.resolve(public_reference(args["handle"]))
            self.upsert_channel(channel)
            self.db.execute(
                "INSERT OR IGNORE INTO sources(channel_id,title) VALUES (?,?)",
                (channel.id, channel.title),
            )
            self.db.event(
                "discovery",
                "Lien accessible enregistré",
                "Autorisations non vérifiées.",
                channel.id,
            )
            return "Entité enregistrée · autorisation à documenter dans Liens & sources"
        if name == "network_link":
            return self.network.link(**args)
        if name == "network_unlink":
            return self.network.unlink(**args)
        if name == "verify_source":
            await self.verify_source(args["source_id"])
            return "Accès confirmé : cette source est téléchargeable."
        if name == "channel_avatar":
            return args["channel_id"], await self.gateway.channel_avatar(
                args["channel_id"], self.paths.root / "avatars"
            )
        if name == "browse_channel_media":
            channel = self.db.one(
                "SELECT * FROM channels WHERE id=?", (args["channel_id"],)
            )
            if not self.gateway.connected:
                raise DomainError("Connectez Telegram pour voir les médias.")
            if not channel or channel["protected"]:
                raise DomainError("Ce canal est inaccessible ou protège ses contenus.")
            limit = int(args.get("limit", 100))
            if not 1 <= limit <= 1000:
                raise DomainError("Limitez l'aperçu aux 1 000 dernières publications.")
            await self.gateway.check_source(channel["id"])
            messages = await self.gateway.recent(channel["id"], limit)
            kind = args.get("kind", "all")
            if kind not in ("all", "photo", "video"):
                raise DomainError("Format non reconnu.")
            return {
                "channel_id": channel["id"],
                "limit": limit,
                "permission_declared": bool(args.get("permission_declared")),
                "messages": [
                    m
                    for m in messages
                    if m["kind"] in ("photo", "video")
                    and (kind == "all" or m["kind"] == kind)
                    and not m["protected"]
                ],
            }
        if name == "import_channel_media":
            if self.auth_lock.locked():
                raise DomainError("Attendez la fin de la connexion Telegram.")
            if not self.gateway.connected:
                raise DomainError("Connectez Telegram pour télécharger.")
            source = await self.prepare_download_source(
                args["channel_id"], args.get("permission_declared", False)
            )
            return self.importer.create(
                source_id=source["id"],
                photos=args.get("photos", True),
                videos=args.get("videos", True),
                selected_ids=args.get("selected_ids"),
            )
        if name == "import_telegram":
            if self.auth_lock.locked():
                raise DomainError(
                    "Attendez la fin de la connexion Telegram avant de télécharger."
                )
            if not self.gateway.connected:
                raise DomainError(
                    "Connectez votre compte Telegram avant de télécharger."
                )
            await self.verify_source(args["source_id"])
            return self.importer.create(**args)
        if name == "auto_import":
            if self.auth_lock.locked():
                raise DomainError("Attendez la fin de la connexion Telegram.")
            source_id = args["source_id"]
            if args["enabled"]:
                if not self.gateway.connected:
                    raise DomainError(
                        "Connectez votre compte Telegram avant d'activer l'importation automatique."
                    )
                source = await self.verify_source(source_id)
                latest = await self.gateway.latest_message_id(source["channel_id"])
                self.db.execute(
                    "UPDATE sources SET auto_import=1,auto_cursor=MAX(auto_cursor,?),auto_checked_at=? WHERE id=?",
                    (latest, now(), source_id),
                )
                return "Importation automatique active · seuls les nouveaux médias seront récupérés."
            self.db.execute("UPDATE sources SET auto_import=0 WHERE id=?", (source_id,))
            for task in self.db.rows(
                "SELECT id,payload FROM tasks WHERE kind='import' AND state IN ('pending','scheduled','running')"
            ):
                payload = json.loads(task["payload"])
                if payload.get("automatic") and payload.get("source_id") == source_id:
                    self.queue.cancel(task["id"])
            return "Importation automatique arrêtée."
        if name == "partner":
            return self.partners.save(**args)
        if name == "partner_optout":
            self.db.execute(
                "UPDATE partners SET opted_out=1,consent=0 WHERE id=?",
                (args["partner_id"],),
            )
            return
        if name == "exchange":
            return self.partners.exchange(**args)
        if name == "exchange_state":
            return self.partners.set_state(**args)
        if name == "exchange_schedule":
            return self.partners.schedule(**args)
        if name == "exchange_verify":
            return await self.monitor.verify_exchange(**args)
        if name == "watch":
            for source in self.db.rows("SELECT id FROM sources WHERE watch=1"):
                await self.monitor.sync(source["id"])
            return "Observation terminée · jusqu'à 50 messages par source"
        if name == "recent":
            messages = await self.gateway.recent(args["channel_id"], 30)
            return messages
        if name == "settings":
            for key, value in args.items():
                if key not in ("blur", "send_interval", "auto_watch"):
                    raise DomainError("Préférence inconnue.")
                if key == "send_interval" and not 60 <= int(value) <= 86400:
                    raise DomainError(
                        "L'espacement doit être compris entre 60 s et 24 h."
                    )
                self.db.set_setting(key, value)
            return "Préférences enregistrées"
        if name == "backup":
            destination = Path(args["path"])
            await asyncio.to_thread(self.db.backup, destination)
            return "Copie SQLite créée. Les médias et la session sont à sauvegarder séparément."
        if name in (
            "restore_session",
            "configure",
            "request_code",
            "sign_in",
            "logout",
            "reset_auth",
            "edit_phone",
        ):
            if self.auth_lock.locked():
                raise DomainError("Une opération de connexion est déjà en cours.")
            async with self.auth_lock:
                return await self.authenticate(name, args)
        raise DomainError("Commande inconnue.")

    async def authenticate(self, name, args):
        if self.demo:
            raise DomainError(
                "Quittez la démonstration et lancez le mode réel pour connecter un compte."
            )
        if name == "restore_session":
            api_id = self.db.setting("api_id")
            # An API hash is needed to construct Telethon's client. Keep it in
            # the macOS Keychain, never in SQLite or a startup argument.
            if (
                not api_id
                or not self.gateway.session_path.with_suffix(".session").is_file()
            ):
                return None
            secret = await asyncio.to_thread(Keychain().get, str(self.paths.root))
            if not secret:
                return None
            await self.gateway.configure(api_id, secret)
            if self.gateway.connected:
                previous = self.db.setting("account_id")
                if previous and previous != str(self.gateway.account_id):
                    await self.gateway.close()
                    raise DomainError(
                        "Cet espace appartient à un autre compte. Utilisez un autre dossier de données."
                    )
                self.db.set_setting("account_id", str(self.gateway.account_id))
            return None
        if self.db.one("SELECT id FROM tasks WHERE state='running'"):
            raise DomainError(
                "Attendez la fin de l'opération en cours avant de modifier la session."
            )
        self.engine.enabled = False
        if name == "configure":
            api_id = args["api_id"] or self.db.setting("api_id")
            secret = args["api_hash"] or await asyncio.to_thread(
                Keychain().get, str(self.paths.root)
            )
            if not secret:
                raise DomainError("Indiquez l'API hash.")
            result = await self.gateway.configure(api_id, secret)
            self.db.set_setting("api_id", api_id)
        elif name == "logout":
            if self.db.one("SELECT id FROM tasks WHERE state='running'"):
                raise DomainError(
                    "Suspendez la file et attendez la fin de l'opération en cours avant la déconnexion."
                )
            self.engine.enabled = False
            result = await self.gateway.logout()
        else:
            result = await getattr(self.gateway, name)(**args)
        if self.gateway.connected:
            previous = self.db.setting("account_id")
            account = str(self.gateway.account_id)
            if previous and previous != account:
                await self.gateway.close()
                raise DomainError(
                    "Cet espace appartient à un autre compte. Utilisez un autre dossier de données."
                )
            self.db.set_setting("account_id", account)
        if name == "configure" and args["remember"]:
            try:
                await asyncio.to_thread(Keychain().set, str(self.paths.root), secret)
            except Exception as exc:
                log_exception(exc, "keychain")
                raise DomainError(
                    "La configuration Telegram a réussi, mais le trousseau n'a pas pu enregistrer l'API hash. Vous pouvez poursuivre ; il faudra le ressaisir au prochain lancement."
                ) from exc
        return result
