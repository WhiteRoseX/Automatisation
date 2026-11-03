"""Single persistent worker. Unknown sends are NEVER automatically retried."""

import asyncio
import errno
import json

from telepilot.diagnostics import log_exception

from .models import DomainError, RateLimited, Rejected, now


class Engine:
    def __init__(self, db, queue, gateway, importer=None):
        self.db, self.queue, self.gateway, self.importer = db, queue, gateway, importer
        self.enabled = False
        self.stopping = False

    def _import_error(self, task, reason):
        if task["kind"] != "import":
            return
        row = self.db.one("SELECT payload FROM tasks WHERE id=?", (task["id"],))
        if row:
            payload = json.loads(row["payload"])
            payload["errors"] = payload.get("errors", 0) + 1
            payload["last_error"] = reason
            self.db.execute(
                "UPDATE tasks SET payload=? WHERE id=?",
                (json.dumps(payload), task["id"]),
            )

    async def tick(self):
        if getattr(self, "auth_lock", None) and self.auth_lock.locked():
            return
        if not self.gateway.connected:
            return
        if float(self.db.setting("flood_until", "0")) > now():
            return
        task = self.queue.claim(imports_only=not self.enabled)
        if not task:
            return
        payload = json.loads(task["payload"])
        sending = False
        try:
            if task["kind"] == "import":
                await self.importer.run(task)
                return
            channel_id = payload["channel_id"]
            # Global minimum spacing persists across restarts; FloodWait can extend it.
            gap = max(60, int(self.db.setting("send_interval", "60")))
            next_allowed = max(
                float(self.db.setting("last_send", "0")) + gap,
                float(self.db.setting("flood_until", "0")),
            )
            if next_allowed > now():
                self.queue.finish(task["id"], "scheduled", delay=next_allowed - now())
                return
            paths = self.queue.library.require_publishable(payload["media_ids"])
            if not await self.gateway.check_destination(channel_id):
                raise DomainError(
                    "Les droits actuels du compte ne permettent pas de publier."
                )
            # Recheck after the network await; rights may have been revoked meanwhile.
            paths = self.queue.library.require_publishable(payload["media_ids"])
            self.db.set_setting("last_send", now())
            sending = True
            ids = await self.gateway.publish(
                channel_id, payload["text"], paths, payload["random_id"]
            )
            if not ids:
                raise RuntimeError("Unconfirmed response")
            self.queue.finish(task["id"], "completed", result=ids)
            self.db.event("publish", "Publication terminée", task["id"], channel_id)
        except RateLimited as exc:
            self._import_error(task, f"Délai Telegram : {exc.seconds} s")
            self.db.set_setting("flood_until", now() + exc.seconds)
            self.queue.finish(
                task["id"],
                "scheduled",
                error=f"Délai Telegram : {exc.seconds} s",
                delay=exc.seconds,
            )
        except (DomainError, Rejected) as exc:
            self._import_error(task, str(exc))
            self.queue.finish(task["id"], "failed", error=str(exc))
        except asyncio.CancelledError:
            self.queue.finish(
                task["id"],
                "unknown" if sending else "pending",
                error="Opération interrompue",
            )
            raise
        except Exception as exc:
            log_exception(exc, "import" if task["kind"] == "import" else "operation")
            # ConnectionError and TimeoutError inherit OSError in Python.
            # They MUST NOT be classified as local file errors: an interrupted
            # publication might already have reached Telegram.
            local_error = isinstance(exc, OSError) and exc.errno in {
                errno.ENOSPC,
                errno.EACCES,
                errno.EPERM,
                errno.EROFS,
                errno.ENOENT,
                errno.ENOTDIR,
                errno.EISDIR,
            }
            if local_error:
                reason = (
                    "Espace disque insuffisant"
                    if exc.errno == errno.ENOSPC
                    else "Erreur de fichier local"
                )
                self._import_error(task, reason)
                self.queue.finish(task["id"], "failed", error=reason)
            else:
                self._import_error(task, "Connexion indisponible")
                # Never include exception text: it may contain private content.
                # Unknown sends must never be retried automatically.
                state = (
                    "unknown"
                    if sending
                    else ("scheduled" if task["attempts"] < 5 else "failed")
                )
                reason = (
                    "Résultat incertain : vérifier Telegram"
                    if sending
                    else "Connexion indisponible"
                )
                self.queue.finish(
                    task["id"], state, error=reason, delay=60 * min(task["attempts"], 5)
                )

    async def run(self):
        while not self.stopping:
            await self.tick()
            await asyncio.sleep(1)
