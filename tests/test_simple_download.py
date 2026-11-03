"""Simple download flow: fake gateway, no real Telegram credentials."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from telepilot.config import Paths
from telepilot.core.models import Channel, DomainError, now
from telepilot.service import ApplicationService


class LocalGateway:
    connected = True
    identity = "Fictitious account"
    sample_content_safe = True
    account_id = "test"

    def __init__(self):
        self.messages = [self._message(i) for i in range(1, 231)]

    @staticmethod
    def _message(i):
        return {"id": i, "date": now(), "kind": "photo", "protected": False,
                "media_id": f"photo-{i}", "album_id": None, "text": f"Media #{i}", "size": 100}

    async def check_source(self, channel_id):
        if channel_id == -1003:
            raise DomainError("Contenu protégé")

    async def channels(self):
        return [Channel(-1001, "Owned", "own", "", True, False, 100, role="owner"),
                Channel(-1002, "Partner", "partner", "", False, False, 100, role="read_only"),
                Channel(-1003, "Protected", "protected", "", False, True, 100, role="read_only")]

    async def recent(self, channel_id, limit):
        return list(reversed(self.messages))[:limit]

    async def selected_media(self, channel_id, ids):
        return [m for m in self.messages if m["id"] in ids and m["id"] != 3]

    async def import_batch(self, channel_id, cursor, start_date, end_date, limit=100):
        return [m for m in self.messages if m["id"] > cursor][:limit]

    async def download(self, channel_id, message_id, directory):
        path = Path(directory) / f"photo-{message_id}.jpg"
        path.write_bytes(f"demo unique image {message_id}".encode())
        return str(path)


class SimpleDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        paths = Paths(Path(self.temp.name))
        paths.prepare()
        self.gateway = LocalGateway()
        self.service = ApplicationService(paths, self.gateway, False)
        await self.service.sync_channels()

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def finish_import(self, task_id):
        for _ in range(15):
            await self.service.engine.tick()
            task = self.service.db.one("SELECT * FROM tasks WHERE id=?", (task_id,))
            if task["state"] in ("completed", "failed"):
                return task
            self.service.db.execute("UPDATE tasks SET due_at=0 WHERE id=?", (task_id,))
        self.fail("Import did not terminate")

    async def test_owned_channel_all_230_messages_without_source_form(self):
        task = await self.service.command("import_channel_media", channel_id=-1001)
        done = await self.finish_import(task)
        self.assertEqual(done["state"], "completed", done["error"])
        self.assertEqual(len(self.service.db.rows("SELECT * FROM provenance")), 230)
        payload = json.loads(done["payload"])
        self.assertEqual(payload["downloaded"], 230)
        self.assertIsNone(payload["maximum"])

    async def test_partner_requires_download_confirmation_but_not_publication_approval(self):
        with self.assertRaises(DomainError):
            await self.service.command("import_channel_media", channel_id=-1002)
        task = await self.service.command("import_channel_media", channel_id=-1002,
                                          permission_declared=True, selected_ids=[2, 3, 4])
        done = await self.finish_import(task)
        self.assertEqual(done["state"], "completed", done["error"])
        payload = json.loads(done["payload"])
        self.assertEqual(payload["downloaded"], 2)
        self.assertEqual(payload["skipped"], 1)
        self.assertEqual(payload["scanned"], 3)
        media = self.service.db.rows("SELECT * FROM media")
        self.assertEqual(len(media), 2)
        self.assertTrue(all(m["rights"] == "unverified" for m in media))
        with self.assertRaises(DomainError):
            self.service.library.require_publishable([media[0]["id"]])

    async def test_protected_source_is_refused(self):
        with self.assertRaises(DomainError):
            await self.service.command("import_channel_media", channel_id=-1003, permission_declared=True)

    async def test_browse_only_lists_accessible_media(self):
        browsed = await self.service.command("browse_channel_media", channel_id=-1002, limit=20, kind="photo")
        self.assertEqual(len(browsed["messages"]), 20)
        self.assertEqual(browsed["messages"][0]["id"], 230)


if __name__ == "__main__":
    unittest.main()
