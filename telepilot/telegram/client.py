import asyncio
import re
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path

from telethon import TelegramClient, errors, functions, types, utils

from telepilot.core.models import (
    Channel,
    DomainError,
    RateLimited,
    Rejected,
    normalize_phone,
)


def translate_limits(method):
    @wraps(method)
    async def wrapped(*args, **kwargs):
        try:
            return await method(*args, **kwargs)
        except (errors.FloodWaitError, errors.SlowModeWaitError) as exc:
            raise RateLimited(exc.seconds) from None

    return wrapped


class TelethonGateway:
    def __init__(self, session_path: Path):
        self.session_path = session_path
        self.client = None
        self.identity = "Non connecté"
        self.connected = False
        self.phone = None
        self.code_hash = None
        self.account_id = None
        self.auth_state = "credentials"
        self.code_delivery = ""

    async def configure(self, api_id, api_hash):
        api_id = str(api_id).strip()
        api_hash = api_hash.strip() if isinstance(api_hash, str) else ""
        if (
            not re.fullmatch(r"[0-9]+", api_id)
            or not 0 < int(api_id) < 2**31
            or not re.fullmatch(r"[0-9a-fA-F]{32}", api_hash)
        ):
            raise DomainError(
                "Vérifiez l’API ID et l’API hash obtenus sur my.telegram.org."
            )
        await self.close()
        self.client = TelegramClient(
            str(self.session_path),
            int(api_id),
            api_hash.strip(),
            request_retries=0,
            connection_retries=3,
            flood_sleep_threshold=0,
            raise_last_call_error=True,
            device_model="TelePilot Desktop",
            app_version="0.6.0",
        )
        try:
            await asyncio.wait_for(self.client.connect(), timeout=45)
            for path in self.session_path.parent.glob("*.session*"):
                path.chmod(0o600)
            return await self.status()
        except BaseException:
            await self.close()
            raise

    async def _auth_call(self, operation):
        # With request_retries=0, Telethon 1.42 switches DC then raises the
        # migration error. Retry only explicit auth migrations, never sends.
        for attempt in range(3):
            try:
                return await asyncio.wait_for(operation(), timeout=45)
            except (
                errors.PhoneMigrateError,
                errors.NetworkMigrateError,
                errors.UserMigrateError,
            ):
                if attempt == 2:
                    raise

    async def status(self):
        authorized = bool(
            self.client and await self._auth_call(self.client.is_user_authorized)
        )
        me = await self._auth_call(self.client.get_me) if authorized else None
        self.connected = me is not None
        if me is not None:
            self.account_id = me.id
            self.identity = (
                " ".join(x for x in (me.first_name, me.last_name) if x)
                or "Compte Telegram"
            )
            self.auth_state = "connected"
            self.phone = self.code_hash = None
            self.code_delivery = ""
        else:
            self.identity = "Non connecté"
            self.account_id = None
            self.auth_state = "phone" if self.client else "credentials"
        return (
            self.identity
            if self.connected
            else "Identifiants configurés. Saisissez maintenant votre numéro de téléphone."
        )

    async def request_code(self, phone):
        if not self.client or self.auth_state == "credentials":
            raise DomainError("Configurez les identifiants API en premier.")
        if self.connected:
            raise DomainError("Le compte est déjà connecté.")
        normalized = normalize_phone(phone)
        sent = await self._auth_call(lambda: self.client.send_code_request(normalized))
        if not getattr(sent, "phone_code_hash", None):
            raise DomainError(
                "Telegram n'a pas confirmé la demande de code. Reconfigurez la session avant de réessayer."
            )
        self.phone = normalized
        self.code_hash = sent.phone_code_hash
        self.auth_state = "code"
        delivery = type(getattr(sent, "type", None)).__name__
        self.code_delivery = {
            "SentCodeTypeApp": "Saisissez le code reçu dans l'application Telegram.",
            "SentCodeTypeSms": "Saisissez le code reçu par SMS.",
            "SentCodeTypeCall": "Saisissez le code communiqué par l'appel Telegram.",
        }.get(delivery, "Saisissez le code reçu par le moyen indiqué par Telegram.")
        return self.code_delivery

    async def sign_in(self, code="", password=""):
        if not self.client:
            raise DomainError("Configurez les identifiants API en premier.")
        if self.connected:
            raise DomainError("Le compte est déjà connecté.")
        try:
            if self.auth_state == "password":
                if not isinstance(password, str) or not password:
                    raise DomainError(
                        "Saisissez le mot de passe de vérification en deux étapes."
                    )
                await self._auth_call(lambda: self.client.sign_in(password=password))
            else:
                if self.auth_state != "code" or not self.phone or not self.code_hash:
                    raise DomainError(
                        "Demandez d'abord un code Telegram pour votre numéro."
                    )
                if password:
                    raise DomainError(
                        "Validez d'abord le code. Le mot de passe ne sera demandé que si Telegram l'exige."
                    )
                normalized = code.strip() if isinstance(code, str) else ""
                if not re.fullmatch(r"[0-9]{1,10}", normalized):
                    raise DomainError("Saisissez le code numérique reçu de Telegram.")
                await self._auth_call(
                    lambda: self.client.sign_in(
                        phone=self.phone,
                        code=normalized,
                        phone_code_hash=self.code_hash,
                    )
                )
        except errors.SessionPasswordNeededError:
            self.auth_state = "password"
            return "Mot de passe 2FA requis"
        except errors.PhoneCodeExpiredError:
            self.auth_state = "phone"
            self.code_hash = None
            raise
        return await self.status()

    async def logout(self):
        if self.client:
            if not await self._auth_call(self.client.log_out):
                raise DomainError(
                    "Telegram n'a pas confirmé la déconnexion. Réessayez."
                )
        await self.close()

    async def reset_auth(self):
        if self.connected:
            raise DomainError(
                "Déconnectez le compte avant de changer ses identifiants."
            )
        await self.close()
        return "Reprenez la configuration des identifiants API."

    async def edit_phone(self):
        if not self.client or self.connected:
            raise DomainError(
                "Le changement de numéro est disponible uniquement pendant la connexion."
            )
        self.phone = self.code_hash = None
        self.code_delivery = ""
        self.auth_state = "phone"
        return "Saisissez votre numéro avant de demander un nouveau code."

    def require(self):
        if not self.connected or not self.client:
            raise DomainError("Connectez votre compte Telegram dans les préférences.")

    @staticmethod
    def channel(entity):
        if not isinstance(entity, (types.Channel, types.Chat)):
            raise DomainError("Cette entité n'est pas un canal ou un groupe Telegram.")
        entity_type = (
            "group"
            if isinstance(entity, types.Chat)
            else "supergroup"
            if entity.megagroup or entity.gigagroup
            else "broadcast"
            if entity.broadcast
            else None
        )
        if not entity_type:
            raise DomainError("Ce type d'entité Telegram n'est pas pris en charge.")
        rights = getattr(entity, "admin_rights", None)
        owner = bool(getattr(entity, "creator", False))
        admin = owner or rights is not None
        unavailable = bool(
            getattr(entity, "left", False)
            or getattr(entity, "deactivated", False)
            or getattr(entity, "migrated_to", None)
        )
        bans = getattr(entity, "banned_rights", None)
        defaults = getattr(entity, "default_banned_rights", None)
        restricted = any(
            getattr(bans, name, False)
            for name in ("view_messages", "send_messages", "send_plain")
        )
        if entity_type == "broadcast":
            can_post = owner or bool(rights and rights.post_messages)
        elif getattr(entity, "gigagroup", False):
            can_post = admin
        else:
            can_post = admin or not any(
                getattr(defaults, name, False)
                for name in ("view_messages", "send_messages", "send_plain")
            )
        can_post = bool(can_post and not restricted and not unavailable)
        role = (
            "owner"
            if owner
            else "admin"
            if admin
            else "member"
            if can_post
            else "read_only"
        )
        username = getattr(entity, "username", None) or ""
        return Channel(
            utils.get_peer_id(entity),
            entity.title,
            username,
            "",
            can_post,
            bool(getattr(entity, "noforwards", False)),
            getattr(entity, "participants_count", None),
            entity_type,
            role,
            "public" if username else "private",
            bool(not unavailable and (owner or (rights and rights.invite_users))),
            bool(getattr(entity, "join_request", False)),
        )

    @translate_limits
    async def channels(self):
        self.require()
        result = []
        async for dialog in self.client.iter_dialogs():
            entity = dialog.entity
            if isinstance(entity, (types.Channel, types.Chat)):
                if isinstance(entity, types.Channel) and not (
                    entity.broadcast or entity.megagroup or entity.gigagroup
                ):
                    continue
                result.append(self.channel(entity))
        return result

    async def resolve(self, handle):
        self.require()
        entity = await self.client.get_entity(handle)
        if not isinstance(entity, (types.Channel, types.Chat)):
            raise DomainError(
                "Choisissez un canal ou un groupe accessible. Les conversations privées ne sont pas ajoutées."
            )
        return self.channel(entity)

    @translate_limits
    async def check_destination(self, channel_id):
        self.require()
        entity = await self.client.get_entity(channel_id)
        return self.channel(entity).can_post

    async def check_source(self, channel_id):
        self.require()
        entity = await self.client.get_entity(channel_id)
        if getattr(entity, "noforwards", False):
            raise DomainError("Ce canal protège ses contenus. Téléchargement interdit.")

    async def publish(self, channel_id, text, paths, random_id):
        self.require()
        try:
            if paths:
                result = await self.client.send_file(
                    channel_id,
                    paths if len(paths) > 1 else paths[0],
                    caption=text,
                    parse_mode=None,
                )
                return [
                    message.id
                    for message in (result if isinstance(result, list) else [result])
                ]
            entity = await self.client.get_input_entity(channel_id)
            result = await self.client(
                functions.messages.SendMessageRequest(
                    entity, text, random_id=random_id, no_webpage=True
                )
            )
            if isinstance(result, types.UpdateShortSentMessage):
                return [result.id]
            return [
                u.id
                for u in getattr(result, "updates", [])
                if isinstance(u, types.UpdateMessageID) and u.random_id == random_id
            ]
        except (errors.FloodWaitError, errors.SlowModeWaitError) as exc:
            raise RateLimited(exc.seconds) from None
        except (
            errors.BadRequestError,
            errors.ForbiddenError,
            errors.UnauthorizedError,
        ):
            raise Rejected(
                "Telegram a refusé la publication. Vérifiez les droits, le contenu et la session."
            ) from None

    @staticmethod
    def message(message):
        kind = "photo" if message.photo else "video" if message.video else "text"
        media = message.document if message.video else message.photo
        size = getattr(media, "size", None)
        if size is None and message.photo:
            size = (
                getattr(message.photo.sizes[-1], "size", None)
                if message.photo.sizes
                else None
            )
        return {
            "id": message.id,
            "text": message.raw_text or "",
            "date": message.date.timestamp(),
            "views": message.views,
            "forwards": message.forwards,
            "reactions": sum(r.count for r in message.reactions.results)
            if message.reactions
            else None,
            "kind": kind,
            "album_id": str(message.grouped_id) if message.grouped_id else None,
            "media_id": str(message.photo.id if message.photo else message.document.id)
            if (message.photo or message.video)
            else None,
            "protected": bool(getattr(message, "noforwards", False)),
            "size": size,
        }

    @translate_limits
    async def recent(self, channel_id, limit=30):
        self.require()
        return [
            self.message(m)
            async for m in self.client.iter_messages(channel_id, limit=limit)
            if m.date
        ]

    @translate_limits
    async def import_batch(self, channel_id, cursor, start_date, end_date, limit=20):
        self.require()
        await self.check_source(channel_id)
        # Oldest first ensures a durable high-water mark. Date filtering is done by the importer.
        result = []
        async for message in self.client.iter_messages(
            channel_id,
            min_id=cursor,
            reverse=True,
            limit=limit,
            offset_date=datetime.fromtimestamp(start_date, UTC)
            if start_date is not None and not cursor
            else None,
        ):
            if message.date:
                result.append(self.message(message))
        return result

    @translate_limits
    async def selected_media(self, channel_id, message_ids):
        self.require()
        await self.check_source(channel_id)
        if not message_ids:
            return []
        messages = await self.client.get_messages(channel_id, ids=message_ids)
        return sorted(
            (
                self.message(m)
                for m in messages
                if m
                and m.date
                and (m.photo or m.video)
                and not getattr(m, "noforwards", False)
            ),
            key=lambda m: m["id"],
        )

    async def latest_message_id(self, channel_id):
        self.require()
        await self.check_source(channel_id)
        messages = await self.client.get_messages(channel_id, limit=1)
        return messages[0].id if messages else 0

    @translate_limits
    async def create_community(self, title, about="", kind="channel"):
        """Create a private Telegram channel or supergroup, only on explicit UI action."""
        self.require()
        title = str(title or "").strip()
        about = str(about or "").strip()
        if not 1 <= len(title) <= 128 or len(about) > 255:
            raise DomainError("Nom ou description invalide.")
        if kind not in ("channel", "group"):
            raise DomainError("Choisissez un canal ou un groupe.")
        result = await self.client(
            functions.channels.CreateChannelRequest(
                title=title,
                about=about,
                broadcast=(kind == "channel"),
                megagroup=(kind == "group"),
            )
        )
        created = next((c for c in result.chats if isinstance(c, types.Channel)), None)
        if created is None:
            raise DomainError("Telegram n'a pas confirmé la création.")
        return self.channel(created)

    async def _existing_partner_dialog(self, handle):
        """Do not initiate cold-message conversations from the app."""
        self.require()
        handle = str(handle or "").strip()
        if not handle:
            raise DomainError("Ce partenaire n'a pas d'identifiant Telegram.")
        target = await self.client.get_entity(handle)
        target_id = utils.get_peer_id(target)
        async for dialog in self.client.iter_dialogs():
            if utils.get_peer_id(dialog.entity) == target_id:
                return target
        raise DomainError("Aucune conversation existante avec ce partenaire. Contactez-le d'abord dans Telegram.")

    @translate_limits
    async def partner_messages(self, handle, limit=40):
        target = await self._existing_partner_dialog(handle)
        messages = await self.client.get_messages(target, limit=max(1, min(80, int(limit))))
        return [
            {"id": message.id, "text": message.raw_text or "",
             "out": bool(message.out), "date": message.date.timestamp() if message.date else None}
            for message in reversed(messages)
        ]

    @translate_limits
    async def reply_to_partner(self, handle, message):
        text = str(message or "").strip()
        if not text or len(text) > 4096:
            raise DomainError("Le message doit contenir entre 1 et 4096 caractères.")
        target = await self._existing_partner_dialog(handle)
        return (await self.client.send_message(target, text)).id

    async def channel_avatar(self, channel_id, directory):
        self.require()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        entity = await self.client.get_entity(channel_id)
        path = await self.client.download_profile_photo(
            entity, file=str(directory / f"{channel_id}.jpg")
        )
        if path:
            Path(path).chmod(0o600)
        return str(path) if path else ""

    @translate_limits
    async def download(self, channel_id, message_id, directory):
        await self.check_source(channel_id)
        message = await self.client.get_messages(channel_id, ids=message_id)
        if not message or getattr(message, "noforwards", False):
            raise DomainError("Message absent ou protégé : importation impossible.")
        if not (message.photo or message.video):
            return None
        return await self.client.download_media(message, file=str(directory) + "/")

    async def close(self):
        client, self.client = self.client, None
        self.connected = False
        self.identity = "Non connecté"
        self.account_id = None
        self.phone = self.code_hash = None
        self.code_delivery = ""
        self.auth_state = "credentials"
        if client:
            await client.disconnect()
