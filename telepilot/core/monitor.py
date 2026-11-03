from .models import ALLOWED_RIGHTS, DomainError, now


class Monitor:
    def __init__(self, db, gateway):
        self.db, self.gateway = db, gateway

    async def sync(self, source_id):
        source = self.db.one("SELECT * FROM sources WHERE id=?", (source_id,))
        if not source or not source["watch"] or source["rights"] not in ALLOWED_RIGHTS:
            raise DomainError("Activez le suivi d'une source autorisée.")
        channel_id = source["channel_id"]
        messages = await self.gateway.recent(channel_id, 50)
        # Bounded observation: absence is not evidence of deletion.
        for message in messages:
            previous = self.db.one("SELECT * FROM observations WHERE channel_id=? AND message_id=?", (channel_id, message["id"]))
            if not previous or previous["text"] != message["text"]:
                keywords = [word.strip().casefold() for word in source["keywords"].split(",") if word.strip()]
                if not keywords or any(word in message["text"].casefold() for word in keywords):
                    self.db.event("new" if not previous else "edited", "Publication observée" if not previous else "Modification observée",
                                  message["text"][:160], channel_id, message["id"])
            self.db.execute("""INSERT INTO observations(channel_id,message_id,text,published_at,views,reactions,forwards,kind,observed_at)
                VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(channel_id,message_id) DO UPDATE SET
                text=excluded.text,views=excluded.views,reactions=excluded.reactions,forwards=excluded.forwards,observed_at=excluded.observed_at""",
                (channel_id,message["id"],message["text"],message["date"],message["views"],message["reactions"],message["forwards"],message["kind"],now()))
        self.db.execute("UPDATE sources SET last_sync=? WHERE id=?", (now(), source_id))
        return messages

    async def verify_exchange(self, exchange_id):
        exchange = self.db.one("SELECT e.*,p.channel_id AS partner_channel FROM exchanges e JOIN partners p ON e.partner_id=p.id WHERE e.id=?", (exchange_id,))
        if not exchange:
            raise DomainError("Échange introuvable.")
        source = self.db.one("SELECT * FROM sources WHERE channel_id=? AND watch=1", (exchange["partner_channel"],))
        if not source or source["rights"] not in ALLOWED_RIGHTS:
            raise DomainError("Le canal partenaire doit être une source dont le suivi est autorisé et activé.")
        messages = await self.sync(source["id"])
        matches = [m for m in messages if exchange["partner_copy"] in m["text"] and
                   (not exchange["expected_link"] or exchange["expected_link"] in m["text"]) and
                   abs(m["date"]-exchange["due_at"]) <= 86400]
        verification = f"Observé · message #{matches[0]['id']} · durée non vérifiée" if matches else "Non retrouvé dans les 50 derniers messages · vérification manuelle requise"
        self.db.execute("UPDATE exchanges SET verification=? WHERE id=?", (verification, exchange_id))
        return verification

