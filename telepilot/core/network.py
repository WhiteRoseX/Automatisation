"""Local network organisation; no implicit mutations of Telegram entities."""

import re
from urllib.parse import urlparse

from .models import DomainError, now


def public_reference(value):
    value = value.strip()
    if value.startswith(("https://", "http://")):
        parsed = urlparse(value)
        if (
            parsed.hostname not in ("t.me", "telegram.me")
            or parsed.query
            or parsed.fragment
        ):
            raise DomainError(
                "Utilisez un identifiant @nom ou un lien public https://t.me/nom."
            )
        value = parsed.path.strip("/")
        value = value.removeprefix("s/")
    value = value.lstrip("@")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", value):
        raise DomainError(
            "Utilisez le lien public d'un canal ou groupe. Les invitations privées et liens de messages ne sont pas ajoutés ici."
        )
    return "@" + value.lower()


class Network:
    def __init__(self, db):
        self.db = db

    def link(self, parent_id, child_id, label=""):
        if parent_id == child_id:
            raise DomainError("Une entité ne peut pas être son propre parent.")
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute(
                    "SELECT COUNT(*) FROM channels WHERE id IN (?,?)",
                    (parent_id, child_id),
                ).fetchone()[0]
                != 2
            ):
                raise DomainError("Sélectionnez deux entités déjà enregistrées.")
            current = parent_id
            visited = {child_id}
            while current is not None:
                if current in visited:
                    raise DomainError(
                        "Cette association créerait une boucle dans le réseau."
                    )
                visited.add(current)
                row = db.execute(
                    "SELECT parent_id FROM network_links WHERE child_id=?", (current,)
                ).fetchone()
                current = row[0] if row else None
            db.execute(
                """INSERT INTO network_links(parent_id,child_id,label,created_at) VALUES (?,?,?,?)
                ON CONFLICT(child_id) DO UPDATE SET parent_id=excluded.parent_id,label=excluded.label,created_at=excluded.created_at""",
                (parent_id, child_id, label.strip()[:2000], now()),
            )
        self.db.event(
            "network",
            "Organisation locale mise à jour",
            "Association enregistrée sans modifier Telegram.",
        )

    def unlink(self, child_id):
        self.db.execute("DELETE FROM network_links WHERE child_id=?", (child_id,))
        self.db.event(
            "network",
            "Association locale retirée",
            "Les entités Telegram restent inchangées.",
        )
