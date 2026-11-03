import asyncio
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telethon import types, utils
from telepilot.config import Paths
from telepilot.core.database import Database, SCHEMA
from telepilot.core.models import Channel, DomainError
from telepilot.core.network import Network, public_reference
from telepilot.service import ApplicationService
from telepilot.telegram.client import TelethonGateway


def channel(entity_id, **kwargs):
    return types.Channel(entity_id, f"Entité {entity_id}", types.ChatPhotoEmpty(), datetime.now(timezone.utc), **kwargs)


def group(entity_id, **kwargs):
    return types.Chat(entity_id, f"Groupe {entity_id}", types.ChatPhotoEmpty(), 12, datetime.now(timezone.utc), 1, **kwargs)


class EntitySynchronization(unittest.IsolatedAsyncioTestCase):
    async def test_sync_includes_broadcast_supergroup_chat_and_excludes_private_users(self):
        entities = [channel(1, broadcast=True, creator=True, username="public_demo"),
                    channel(2, megagroup=True, admin_rights=types.ChatAdminRights(invite_users=True)),
                    group(3), types.User(4, first_name="Private"),
                    channel(5, broadcast=True), channel(6, megagroup=True, left=True)]
        class Client:
            async def iter_dialogs(self):
                for entity in entities:
                    yield SimpleNamespace(entity=entity)
        gateway = TelethonGateway(Path("unused"))
        gateway.client = Client()
        gateway.connected = True
        rows = await gateway.channels()
        self.assertEqual(len(rows), 5)
        self.assertEqual([r.entity_type for r in rows], ["broadcast", "supergroup", "group", "broadcast", "supergroup"])
        self.assertEqual([r.role for r in rows], ["owner", "admin", "member", "read_only", "read_only"])
        self.assertEqual([r.can_post for r in rows], [True, True, True, False, False])
        self.assertEqual(rows[0].visibility, "public")
        self.assertEqual(rows[1].visibility, "private")
        self.assertTrue(rows[1].can_invite)
        self.assertEqual(rows[2].id, -3)
        self.assertEqual(rows[0].id, utils.get_peer_id(entities[0]))

    async def test_admin_role_does_not_imply_broadcast_post_permission(self):
        result = TelethonGateway.channel(channel(1, broadcast=True, admin_rights=types.ChatAdminRights(change_info=True)))
        self.assertEqual(result.role, "admin")
        self.assertFalse(result.can_post)

    async def test_group_defaults_individual_bans_left_and_migration_are_respected(self):
        bans = types.ChatBannedRights(until_date=None, send_messages=True)
        read_only = channel(1, megagroup=True, default_banned_rights=bans)
        muted = channel(2, megagroup=True, banned_rights=bans)
        migrated = group(3, migrated_to=types.InputChannel(10, 12))
        for entity in (read_only, muted, migrated, group(4, left=True)):
            with self.subTest(entity=entity.id):
                self.assertFalse(TelethonGateway.channel(entity).can_post)
        admin = channel(5, megagroup=True, default_banned_rights=bans, admin_rights=types.ChatAdminRights())
        self.assertTrue(TelethonGateway.channel(admin).can_post)

    async def test_private_conversation_cannot_be_resolved_as_destination(self):
        gateway = TelethonGateway(Path("unused"))
        gateway.connected = True
        gateway.client = SimpleNamespace(get_entity=AsyncMock(return_value=types.User(1)))
        with self.assertRaises(DomainError):
            await gateway.resolve("@person")
        with self.assertRaises(DomainError):
            await gateway.check_destination(1)

    async def test_live_destination_recheck_recognizes_group_permission_loss(self):
        gateway = TelethonGateway(Path("unused"))
        gateway.connected = True
        gateway.client = SimpleNamespace(get_entity=AsyncMock(return_value=group(1, creator=True)))
        self.assertTrue(await gateway.check_destination(-1))
        gateway.client.get_entity.return_value = group(1, left=True)
        self.assertFalse(await gateway.check_destination(-1))

    async def test_service_sync_preserves_notes_and_revokes_stale_rights(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = Paths(Path(directory)); paths.prepare()
            gateway = SimpleNamespace(connected=True, identity="Test", channels=AsyncMock(return_value=[
                Channel(-1, "Groupe", can_post=True, entity_type="group", role="owner")]))
            service = ApplicationService(paths, gateway, False)
            await service.sync_channels()
            service.db.execute("UPDATE channels SET notes='Conserver',category='Privé' WHERE id=-1")
            gateway.channels.return_value = [Channel(-1, "Groupe renommé", entity_type="group", role="read_only")]
            await service.sync_channels()
            row = service.snapshot()["channels"][0]
            self.assertEqual(row["notes"], "Conserver")
            self.assertEqual(row["category"], "Privé")
            self.assertEqual(row["title"], "Groupe renommé")
            self.assertFalse(row["can_post"])
            gateway.channels.return_value = []
            await service.sync_channels()
            self.assertEqual(service.snapshot()["channels"][0]["role"], "unknown")

    async def test_registering_same_public_entity_never_duplicates_or_grants_rights(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = Paths(Path(directory)); paths.prepare()
            gateway = SimpleNamespace(connected=True, identity="Test", resolve=AsyncMock(return_value=Channel(-10, "Source", username="source")))
            service = ApplicationService(paths, gateway, False)
            await service.command("resolve_channel", handle="https://t.me/source")
            await service.command("resolve_channel", handle="@SOURCE")
            self.assertEqual(len(service.snapshot()["channels"]), 1)
            self.assertEqual(len(service.snapshot()["sources"]), 1)
            self.assertEqual(service.snapshot()["sources"][0]["rights"], "unverified")
            self.assertEqual(service.snapshot()["sources"][0]["watch"], 0)
            gateway.resolve.assert_awaited_with("@source")


class MigrationAndOrganisation(unittest.TestCase):
    def test_version_one_migrates_without_losing_notes_tasks_or_rights_and_has_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "app.sqlite3"
            connection = sqlite3.connect(path)
            try:
                connection.executescript(SCHEMA + "PRAGMA user_version=1;")
                connection.execute("INSERT INTO channels(id,title,username,notes,can_post) VALUES (1,'Canal','public_name','Notes privées',1)")
                connection.execute("INSERT INTO sources(channel_id,title,rights,evidence) VALUES (1,'Source','partner','Accord écrit')")
                connection.execute("INSERT INTO tasks(id,kind,title,state,payload,due_at,created_at,updated_at) VALUES ('task','publish','Brouillon','draft','{}',1,1,1)")
                connection.commit()
            finally:
                connection.close()
            db = Database(path)
            self.assertEqual(db.one("PRAGMA user_version")["user_version"], 3)
            row = db.one("SELECT * FROM channels")
            self.assertEqual(row["notes"], "Notes privées")
            self.assertEqual(row["visibility"], "public")
            self.assertEqual(row["role"], "unknown")
            self.assertEqual(db.one("SELECT * FROM sources")["rights"], "partner")
            self.assertEqual(db.one("SELECT auto_import FROM sources")["auto_import"], 0)
            self.assertEqual(db.one("SELECT * FROM tasks")["state"], "draft")
            backup = path.with_name(path.name + ".before-v2.backup")
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            connection = sqlite3.connect(backup)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT notes FROM channels").fetchone()[0], "Notes privées")
            finally:
                connection.close()
            stamp = backup.stat().st_mtime_ns
            Database(path)
            self.assertEqual(backup.stat().st_mtime_ns, stamp)
            self.assertEqual(path.with_name(path.name + ".before-v3.backup").stat().st_mode & 0o777, 0o600)

    def test_organisation_is_durable_and_refuses_cycles_or_missing_entities(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "app.sqlite3")
            for identifier in (1, 2, 3):
                db.execute("INSERT INTO channels(id,title) VALUES (?,?)", (identifier, str(identifier)))
            network = Network(db)
            network.link(1, 2, "Privé")
            network.link(2, 3)
            with self.assertRaises(DomainError): network.link(3, 1)
            with self.assertRaises(DomainError): network.link(1, 1)
            with self.assertRaises(DomainError): network.link(1, 999)
            reopened = Database(db.path)
            self.assertEqual(len(reopened.rows("SELECT * FROM network_links")), 2)
            network.unlink(2)
            self.assertEqual(len(db.rows("SELECT * FROM channels")), 3)
            self.assertEqual(len(db.rows("SELECT * FROM network_links")), 1)

    def test_public_discovery_rejects_invites_and_unrelated_urls(self):
        self.assertEqual(public_reference("https://t.me/s/Example"), "@example")
        for value in ("https://evil.example/t.me/name", "https://t.me/+private", "https://t.me/joinchat/secret", "https://t.me/c/123/1", "https://t.me/name?token=secret", "@bad/name"):
            with self.subTest(value=value), self.assertRaises(DomainError): public_reference(value)

