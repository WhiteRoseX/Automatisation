from .models import DomainError, EXCHANGE_STATES, now


class Partners:
    def __init__(self, db, queue):
        self.db, self.queue = db, queue

    def save(self, name, handle="", channel_id=None, category="", audience=None, consent=False, notes="", terms=""):
        if not name.strip():
            raise DomainError("Indiquez un nom de partenaire.")
        if audience is not None and audience < 0:
            raise DomainError("L'audience doit être positive.")
        return self.db.execute("INSERT INTO partners(name,handle,channel_id,category,audience,consent,notes,terms) VALUES (?,?,?,?,?,?,?,?)",
                               (name.strip(), handle.strip(), channel_id, category, audience, int(consent), notes, terms))

    def exchange(self, partner_id, channel_id, title, own_copy, partner_copy, due_at, duration_hours, terms, expected_link=""):
        partner = self.db.one("SELECT * FROM partners WHERE id=?", (partner_id,))
        channel = self.db.one("SELECT * FROM channels WHERE id=? AND can_post=1", (channel_id,))
        if not partner or not partner["channel_id"] or not channel or partner["channel_id"] == channel_id:
            raise DomainError("L'échange nécessite un partenaire avec son canal et un canal de destination distinct que vous administrez.")
        if not title.strip() or not own_copy.strip() or not partner_copy.strip() or duration_hours < 1:
            raise DomainError("Complétez les deux textes publicitaires, le titre et la durée.")
        return self.db.execute("""INSERT INTO exchanges(partner_id,channel_id,title,own_copy,partner_copy,due_at,duration_hours,terms,expected_link)
            VALUES (?,?,?,?,?,?,?,?,?)""", (partner_id, channel_id, title, own_copy, partner_copy, due_at, duration_hours, terms, expected_link))

    def set_state(self, exchange_id, state):
        if state not in EXCHANGE_STATES:
            raise DomainError("État inconnu.")
        row = self.db.one("SELECT task_id FROM exchanges WHERE id=?", (exchange_id,))
        if row and row["task_id"] and state in ("Annulé", "Refusé", "Litige"):
            task = self.db.one("SELECT state FROM tasks WHERE id=?", (row["task_id"],))
            if task and task["state"] in ("draft", "pending", "scheduled"):
                self.queue.cancel(row["task_id"])
        self.db.execute("UPDATE exchanges SET state=? WHERE id=?", (state, exchange_id))
        self.db.event("exchange", "Échange mis à jour", f"#{exchange_id} · {state}")

    def schedule(self, exchange_id):
        row = self.db.one("SELECT * FROM exchanges WHERE id=?", (exchange_id,))
        if not row or row["state"] != "Accord conclu" or row["task_id"]:
            raise DomainError("Validez d'abord un accord. Un échange ne peut être programmé qu'une seule fois.")
        # Stable id makes recovery safe if the app stops after insertion but before linking.
        task_id = self.queue.publication(row["channel_id"], row["own_copy"], due_at=row["due_at"], draft=False,
                                         task_id=f"exchange_{exchange_id}")
        self.db.execute("UPDATE exchanges SET task_id=?,state='Publication programmée' WHERE id=?", (task_id, exchange_id))
        return task_id

