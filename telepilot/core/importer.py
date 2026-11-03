"""Durable, incremental Telegram media imports. Publishing rights stay separate."""
import asyncio
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from .models import ALLOWED_RIGHTS, DomainError, now


def downloadable_source(source):
    if not source or source["protected"]:
        return False
    evidence = (source.get("evidence") or "").strip()
    return bool((source["rights"] in ALLOWED_RIGHTS and evidence)
                or evidence.startswith("download-confirmed:"))


class Importer:
    def __init__(self, db, library, queue, gateway):
        self.db, self.library, self.queue, self.gateway = db, library, queue, gateway

    def create(self, source_id, start_date=None, end_date=None, maximum=None, photos=True, videos=True,
               destination=None, skip_existing=True, automatic=False, cursor=0, selected_ids=None):
        source = self.db.one("SELECT s.*,c.protected FROM sources s LEFT JOIN channels c ON c.id=s.channel_id WHERE s.id=?", (source_id,))
        if not source or not source["channel_id"] or not downloadable_source(source):
            raise DomainError("Source indisponible, protégée ou sans autorisation de téléchargement.")
        if selected_ids is not None:
            if not isinstance(selected_ids, list) or not selected_ids or len(selected_ids) > 1000 or any(
                type(i) is not int or i <= 0 for i in selected_ids
            ):
                raise DomainError("Choisissez entre 1 et 1 000 publications valides.")
            selected_ids = sorted(set(selected_ids))
        if (start_date is not None and end_date is not None and start_date > end_date) or (maximum is not None and not 1 <= maximum <= 100000) or not (photos or videos):
            raise DomainError("Vérifiez la période, les formats et la limite de messages.")
        if destination:
            folder = Path(destination).expanduser()
            if not folder.is_dir() or not os.access(folder, os.W_OK):
                raise DomainError("Le dossier de destination n'est pas accessible en écriture.")
            destination = str(folder.resolve())
        payload = {"source_id": source_id, "channel_id": source["channel_id"], "start": start_date,
                   "end": end_date, "maximum": maximum, "photos": bool(photos), "videos": bool(videos),
                   "cursor": int(cursor), "scanned": 0, "found": 0, "downloaded": 0, "skipped": 0,
                   "errors": 0, "last_error": "", "destination": destination, "skip_existing": bool(skip_existing),
                   "automatic": bool(automatic), "selected_ids": selected_ids}
        task_id = uuid.uuid4().hex
        self.db.execute("INSERT INTO tasks(id,kind,title,state,payload,due_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                        (task_id, "import", "Téléchargement · " + source["title"], "pending", json.dumps(payload), now(), now(), now()))
        self.db.event("import", "Téléchargement lancé", source["title"])
        return task_id

    def _save_progress(self, task_id, p):
        self.db.execute("UPDATE tasks SET payload=?,progress=?,updated_at=? WHERE id=?",
                        (json.dumps(p), p["scanned"], now(), task_id))
        if p.get("automatic"):
            self.db.execute("UPDATE sources SET auto_cursor=MAX(auto_cursor,?) WHERE id=? AND auto_import=1",
                            (p["cursor"], p["source_id"]))

    @staticmethod
    def _ensure_space(directory, expected=0):
        try:
            free = shutil.disk_usage(directory).free
        except OSError:
            raise DomainError("Impossible de vérifier l'espace disque disponible.") from None
        if free < max(int(expected or 0), 0) + 64 * 1024 * 1024:
            raise DomainError("Espace disque insuffisant pour poursuivre le téléchargement.")

    @staticmethod
    def _export(path, folder, source_id, message_id):
        target = Path(folder) / f"{source_id}-{message_id}-{Path(path).name}"
        if target.exists():
            return
        fd, temporary = tempfile.mkstemp(dir=folder, prefix=".telepilot-")
        try:
            with os.fdopen(fd, "wb") as output, open(path, "rb") as original:
                shutil.copyfileobj(original, output, 1024 * 1024)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)

    async def run(self, task):
        p = json.loads(task["payload"])
        source = self.db.one("SELECT s.*,c.protected FROM sources s LEFT JOIN channels c ON c.id=s.channel_id WHERE s.id=?", (p["source_id"],))
        if not downloadable_source(source):
            raise DomainError("L'autorisation ou l'accès de la source n'est plus valide.")
        if p.get("automatic") and not source["auto_import"]:
            self.queue.cancel(task["id"])
            return
        maximum = p.get("maximum")
        remaining = maximum - p["scanned"] if maximum is not None else 100
        if maximum is not None and remaining <= 0:
            self.queue.finish(task["id"], "completed")
            return
        limit = min(100, remaining)
        selected = p.get("selected_ids") is not None
        if selected:
            ids = [mid for mid in p["selected_ids"] if mid > p["cursor"]]
            if not ids:
                self.queue.finish(task["id"], "completed")
                return
            requested = ids[:limit]
            # Iterate requested IDs, including deleted/unavailable messages, so
            # the cursor always records exactly what has been considered.
            returned = {m["id"]: m for m in await self.gateway.selected_media(p["channel_id"], requested)}
            batch = [(mid, returned.get(mid)) for mid in requested]
            done = len(ids) <= limit
        else:
            retrieved = await self.gateway.import_batch(p["channel_id"], p["cursor"], p.get("start"), p.get("end"), limit)
            batch = [(m["id"], m) for m in retrieved]
            done = len(retrieved) < limit
        for message_id, message in batch:
            status = self.db.one("SELECT state,paused FROM tasks WHERE id=?", (task["id"],))
            if not status or status["state"] == "cancelled":
                return
            if status["paused"]:
                self.queue.finish(task["id"], "pending")
                return
            if p.get("automatic") and not self.db.one("SELECT auto_import FROM sources WHERE id=?", (p["source_id"],))["auto_import"]:
                self.queue.cancel(task["id"])
                return
            if message is None:
                p["skipped"] += 1
                p["cursor"] = message_id
                p["scanned"] += 1
                self._save_progress(task["id"], p)
                continue
            if p.get("end") is not None and message["date"] > p["end"]:
                done = True
                break
            eligible = (p.get("start") is None or message["date"] >= p["start"]) and (
                (message["kind"] == "photo" and p["photos"]) or (message["kind"] == "video" and p["videos"]))
            if eligible:
                p["found"] += 1
                exists = self.db.one("SELECT id FROM provenance WHERE source_id=? AND message_id=?", (p["source_id"], message["id"]))
                if exists and p.get("skip_existing", True):
                    p["skipped"] += 1
                elif message["protected"]:
                    p["errors"] += 1
                    p["last_error"] = "Un média protégé par Telegram a été ignoré."
                else:
                    self._ensure_space(self.library.directory, message.get("size") or 0)
                    with tempfile.TemporaryDirectory(dir=self.library.directory, prefix=".download-") as temporary:
                        path = await self.gateway.download(p["channel_id"], message["id"], Path(temporary))
                        status = self.db.one("SELECT state,paused FROM tasks WHERE id=?", (task["id"],))
                        if not status or status["state"] == "cancelled":
                            return
                        if path:
                            self._ensure_space(self.library.directory, Path(path).stat().st_size)
                            if p.get("destination"):
                                self._ensure_space(p["destination"], Path(path).stat().st_size)
                            await asyncio.to_thread(self.library.import_file, path, source_id=p["source_id"],
                                message_id=message["id"], telegram_media_id=message["media_id"], album_id=message["album_id"],
                                message_date=message["date"], caption=message["text"], rights="unverified", evidence=source["evidence"],
                                sensitive=not getattr(self.gateway, "sample_content_safe", False))
                            if p.get("destination"):
                                await asyncio.to_thread(self._export, path, p["destination"], p["source_id"], message["id"])
                            p["downloaded"] += 1
                        else:
                            p["skipped"] += 1
            p["cursor"] = message["id"]
            p["scanned"] += 1
            self._save_progress(task["id"], p)
            if maximum is not None and p["scanned"] >= maximum:
                done = True
                break
            if status and status["paused"]:
                self.queue.finish(task["id"], "pending")
                return
        self.queue.finish(task["id"], "completed" if done else "pending", delay=0 if done else 1)
