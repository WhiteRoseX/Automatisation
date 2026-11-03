import json
import secrets
import uuid
from .models import DomainError, now


class TaskQueue:
    def __init__(self, db, library):
        self.db, self.library = db, library

    def publication(self, channel_id, text, media_ids=(), due_at=None, draft=True, credit="", allow_repeat=False, task_id=None):
        if task_id and self.db.one("SELECT id FROM tasks WHERE id=?", (task_id,)):
            return task_id
        media_ids = list(dict.fromkeys(media_ids))
        channel = self.db.one("SELECT * FROM channels WHERE id=?", (channel_id,))
        if not channel or not channel["can_post"]:
            raise DomainError("Ce canal ne permet pas la publication.")
        text = text.strip()
        if not text and not media_ids:
            raise DomainError("Ajoutez du texte ou un média.")
        if len(media_ids) > 10:
            raise DomainError("Un album peut contenir au maximum 10 médias.")
        combined = text + ("\n\nCrédit : " + credit.strip() if credit.strip() else "")
        # Telegram limits are UTF-16 code units.
        if len(combined.encode("utf-16-le")) // 2 > (1024 if media_ids else 4096):
            raise DomainError("Texte trop long : 1 024 caractères pour une légende, 4 096 pour un message (UTF-16).")
        if not draft:
            self.library.require_publishable(media_ids)
            if not allow_repeat:
                for media_id in media_ids:
                    for previous in self.db.rows("SELECT t.payload FROM tasks t JOIN task_media m ON m.task_id=t.id WHERE m.media_id=? AND t.state IN ('pending','scheduled','running','completed','unknown')", (media_id,)):
                        if json.loads(previous["payload"])["channel_id"] == channel_id:
                            raise DomainError("Un média est déjà prévu ou publié sur ce canal. Confirmez explicitement la répétition.")
        due_at = due_at if due_at is not None else now()
        task_id = task_id or uuid.uuid4().hex
        payload = {"channel_id": channel_id, "text": combined, "media_ids": media_ids, "random_id": secrets.randbits(63)}
        state = "draft" if draft else ("scheduled" if due_at > now() + 5 else "pending")
        with self.db.connect() as db:
            db.execute("INSERT INTO tasks(id,kind,title,state,payload,due_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                       (task_id, "publish", text[:80] or "Album média", state, json.dumps(payload), due_at, now(), now()))
            db.executemany("INSERT INTO task_media VALUES (?,?)", [(task_id, x) for x in media_ids])
        self.db.event("task", "Brouillon enregistré" if draft else "Publication validée", task_id)
        return task_id

    def recover(self):
        with self.db.connect() as db:
            db.execute("UPDATE tasks SET state='unknown',error='Interruption : vérifier Telegram avant toute nouvelle publication',updated_at=? WHERE state='running' AND kind='publish'", (now(),))
            db.execute("UPDATE tasks SET state='pending',error='Importation reprise après interruption',updated_at=? WHERE state='running' AND kind='import'", (now(),))

    def claim(self, imports_only=False):
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE state IN ('pending','scheduled') AND paused=0 AND due_at<=? AND (?=0 OR kind='import') ORDER BY due_at,created_at LIMIT 1", (now(), int(imports_only))).fetchone()
            if not row:
                return None
            db.execute("UPDATE tasks SET state='running',attempts=attempts+1,updated_at=? WHERE id=?", (now(), row["id"]))
            result = dict(row)
            result["attempts"] += 1
            return result

    def finish(self, task_id, state, *, result=None, error="", delay=0):
        with self.db.connect() as db:
            db.execute("UPDATE tasks SET state=?,error=?,result=COALESCE(?,result),due_at=CASE WHEN ?>0 THEN ? ELSE due_at END,updated_at=? WHERE id=? AND state='running'",
                       (state, error, json.dumps(result) if result is not None else None, delay, now()+delay, now(), task_id))

    def cancel(self, task_id):
        row = self.db.one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not row or row["state"] in ("completed", "unknown") or (row["state"] == "running" and row["kind"] == "publish"):
            raise DomainError("Une publication déjà envoyée ou en cours ne peut pas être annulée ici.")
        self.db.execute("UPDATE tasks SET state='cancelled',updated_at=? WHERE id=?", (now(), task_id))

    def pause(self, task_id):
        self.db.execute("UPDATE tasks SET paused=1-paused WHERE id=? AND kind='import' AND state IN ('pending','scheduled','running')", (task_id,))

    def resolve(self, task_id, message_ids):
        if not message_ids:
            raise DomainError("Indiquez au moins un identifiant de publication vérifié sur Telegram.")
        self.db.execute("UPDATE tasks SET state='completed',result=?,error='Résolution manuelle après vérification',updated_at=? WHERE id=? AND state='unknown'", (json.dumps(message_ids), now(), task_id))
        self.db.event("task", "Publication vérifiée manuellement", task_id)

