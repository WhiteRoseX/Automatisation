from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
import time
import re


class DomainError(ValueError):
    """An expected, safe-to-display validation failure."""


def normalize_phone(phone):
    if not isinstance(phone, str):
        raise DomainError("Saisissez votre numéro de téléphone au format international, par exemple +33…")
    normalized = re.sub(r"[\s().-]", "", phone)
    if not re.fullmatch(r"\+[1-9][0-9]{6,14}", normalized):
        raise DomainError("Saisissez un numéro international complet commençant par + et l'indicatif du pays.")
    return normalized


class Rights(StrEnum):
    OWN = "own"
    PARTNER = "partner"
    LICENSED = "licensed"
    UNVERIFIED = "unverified"
    FORBIDDEN = "forbidden"
    PROTECTED = "protected"


ALLOWED_RIGHTS = {Rights.OWN, Rights.PARTNER, Rights.LICENSED}
RIGHT_LABELS = {
    "own": "Contenu personnel", "partner": "Partenaire autorisé",
    "licensed": "Licence documentée", "unverified": "À vérifier",
    "forbidden": "Publication interdite", "protected": "Protégé par Telegram",
}
STATES = ("draft", "pending", "scheduled", "running", "completed", "failed", "cancelled", "unknown")
STATE_LABELS = dict(zip(STATES, ("Brouillon", "En attente", "Programmée", "En cours", "Terminée", "Échec", "Annulée", "À vérifier")))
EXCHANGE_STATES = ("Nouveau", "Contact établi", "Proposition reçue", "Proposition envoyée", "Négociation", "En attente de validation", "Accord conclu", "Publication programmée", "En cours", "Échange terminé", "Refusé", "Annulé", "Litige")
ENTITY_LABELS = {"broadcast": "Canal", "supergroup": "Supergroupe", "group": "Groupe"}
ROLE_LABELS = {"owner": "Propriétaire", "admin": "Administrateur", "member": "Membre", "read_only": "Lecture seule", "unknown": "À synchroniser"}


def now() -> float:
    return time.time()


@dataclass(frozen=True)
class Channel:
    id: int
    title: str
    username: str = ""
    description: str = ""
    can_post: bool = False
    protected: bool = False
    subscribers: int | None = None
    entity_type: str = "broadcast"
    role: str = "unknown"
    visibility: str = "private"
    can_invite: bool = False
    join_request: bool = False


class RateLimited(Exception):
    def __init__(self, seconds: int):
        self.seconds = max(1, seconds)


class Rejected(Exception):
    """Telegram explicitly rejected the operation; no send occurred."""


class TelegramGateway(Protocol):
    connected: bool
    identity: str
    async def channels(self) -> list[Channel]: ...
    async def check_destination(self, channel_id: int) -> bool: ...
    async def publish(self, channel_id: int, text: str, paths: list[str], random_id: int) -> list[int]: ...
    async def recent(self, channel_id: int, limit: int = 30) -> list[dict]: ...
    async def close(self) -> None: ...

