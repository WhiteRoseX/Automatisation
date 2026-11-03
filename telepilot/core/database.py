"""Versioned SQLite storage. Connections are short-lived and local to each thread."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .models import now

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS channels (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, username TEXT NOT NULL DEFAULT '',
 description TEXT NOT NULL DEFAULT '', can_post INTEGER NOT NULL DEFAULT 0,
 protected INTEGER NOT NULL DEFAULT 0, subscribers INTEGER,
 category TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', synced_at REAL);
CREATE TABLE IF NOT EXISTS sources (
 id INTEGER PRIMARY KEY, channel_id INTEGER UNIQUE REFERENCES channels(id), title TEXT NOT NULL,
 rights TEXT NOT NULL DEFAULT 'unverified', evidence TEXT NOT NULL DEFAULT '',
 watch INTEGER NOT NULL DEFAULT 0, keywords TEXT NOT NULL DEFAULT '', last_sync REAL,
 cursor INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS media (
 id INTEGER PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, path TEXT NOT NULL,
 name TEXT NOT NULL, kind TEXT NOT NULL, size INTEGER NOT NULL,
 caption TEXT NOT NULL DEFAULT '', rights TEXT NOT NULL DEFAULT 'unverified',
 evidence TEXT NOT NULL DEFAULT '', sensitive INTEGER NOT NULL DEFAULT 1,
 reviewed INTEGER NOT NULL DEFAULT 0, favorite INTEGER NOT NULL DEFAULT 0,
 revoked INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS provenance (
 id INTEGER PRIMARY KEY, media_id INTEGER NOT NULL REFERENCES media(id),
 source_id INTEGER REFERENCES sources(id), message_id INTEGER, telegram_media_id TEXT,
 album_id TEXT, UNIQUE(source_id,message_id));
CREATE TABLE IF NOT EXISTS tasks (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('draft','pending','scheduled','running','completed','failed','cancelled','unknown')),
 payload TEXT NOT NULL, due_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 paused INTEGER NOT NULL DEFAULT 0, progress INTEGER NOT NULL DEFAULT 0,
 error TEXT NOT NULL DEFAULT '', result TEXT NOT NULL DEFAULT '[]',
 created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS tasks_due ON tasks(state,due_at);
CREATE TABLE IF NOT EXISTS task_media (
 task_id TEXT NOT NULL REFERENCES tasks(id), media_id INTEGER NOT NULL REFERENCES media(id),
 PRIMARY KEY(task_id,media_id));
CREATE TABLE IF NOT EXISTS partners (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, handle TEXT NOT NULL DEFAULT '',
 channel_id INTEGER REFERENCES channels(id), category TEXT NOT NULL DEFAULT '',
 audience INTEGER, consent INTEGER NOT NULL DEFAULT 0, opted_out INTEGER NOT NULL DEFAULT 0,
 notes TEXT NOT NULL DEFAULT '', terms TEXT NOT NULL DEFAULT '', last_contact REAL);
CREATE TABLE IF NOT EXISTS exchanges (
 id INTEGER PRIMARY KEY, partner_id INTEGER NOT NULL REFERENCES partners(id),
 channel_id INTEGER NOT NULL REFERENCES channels(id), title TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'Nouveau', own_copy TEXT NOT NULL DEFAULT '',
 partner_copy TEXT NOT NULL DEFAULT '', expected_link TEXT NOT NULL DEFAULT '',
 due_at REAL NOT NULL, duration_hours INTEGER NOT NULL DEFAULT 24,
 terms TEXT NOT NULL DEFAULT '', verification TEXT NOT NULL DEFAULT 'Non vérifié',
 task_id TEXT REFERENCES tasks(id));
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, created_at REAL NOT NULL, kind TEXT NOT NULL,
 title TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', channel_id INTEGER,
 message_id INTEGER, UNIQUE(kind,channel_id,message_id,detail));
CREATE TABLE IF NOT EXISTS observations (
 channel_id INTEGER NOT NULL, message_id INTEGER NOT NULL, text TEXT NOT NULL,
 published_at REAL NOT NULL, views INTEGER, reactions INTEGER, forwards INTEGER,
 kind TEXT NOT NULL, observed_at REAL NOT NULL, PRIMARY KEY(channel_id,message_id));
CREATE TABLE IF NOT EXISTS metrics (
 id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL REFERENCES channels(id),
 captured_at REAL NOT NULL, subscribers INTEGER);
"""

MIGRATION_2 = """
ALTER TABLE channels ADD COLUMN entity_type TEXT NOT NULL DEFAULT 'broadcast';
ALTER TABLE channels ADD COLUMN role TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE channels ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private';
ALTER TABLE channels ADD COLUMN can_invite INTEGER NOT NULL DEFAULT 0;
ALTER TABLE channels ADD COLUMN join_request INTEGER NOT NULL DEFAULT 0;
UPDATE channels SET visibility='public' WHERE username!='';
CREATE TABLE network_links (
 parent_id INTEGER NOT NULL REFERENCES channels(id),
 child_id INTEGER NOT NULL UNIQUE REFERENCES channels(id),
 label TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL,
 PRIMARY KEY(parent_id,child_id), CHECK(parent_id != child_id));
"""

MIGRATION_3 = """
ALTER TABLE sources ADD COLUMN auto_import INTEGER NOT NULL DEFAULT 0;
ALTER TABLE sources ADD COLUMN auto_cursor INTEGER NOT NULL DEFAULT 0;
ALTER TABLE sources ADD COLUMN auto_checked_at REAL NOT NULL DEFAULT 0;
ALTER TABLE sources ADD COLUMN download_checked_at REAL NOT NULL DEFAULT 0;
ALTER TABLE sources ADD COLUMN download_error TEXT NOT NULL DEFAULT '';
ALTER TABLE provenance ADD COLUMN message_date REAL;
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 3:
                raise RuntimeError(
                    "Cette base nécessite une version plus récente de TelePilot."
                )
            db.execute("PRAGMA journal_mode=WAL")
            if version < 1:
                db.executescript(
                    "BEGIN IMMEDIATE;" + SCHEMA + "PRAGMA user_version=1; COMMIT;"
                )
                version = 1
            if version < 2:
                # Consistent backup before altering an existing schema. Includes WAL data.
                backup_path = path.with_name(path.name + ".before-v2.backup")
                target = sqlite3.connect(backup_path)
                try:
                    db.backup(target)
                finally:
                    target.close()
                backup_path.chmod(0o600)
                db.executescript(
                    "BEGIN IMMEDIATE;" + MIGRATION_2 + "PRAGMA user_version=2; COMMIT;"
                )
                version = 2
            if version < 3:
                backup_path = path.with_name(path.name + ".before-v3.backup")
                target = sqlite3.connect(backup_path)
                try:
                    db.backup(target)
                finally:
                    target.close()
                backup_path.chmod(0o600)
                db.executescript(
                    "BEGIN IMMEDIATE;" + MIGRATION_3 + "PRAGMA user_version=3; COMMIT;"
                )
        path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def rows(self, sql, args=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.rows(sql, args)
        return rows[0] if rows else None

    def execute(self, sql, args=()):
        with self.connect() as db:
            return db.execute(sql, args).lastrowid

    def setting(self, key, default=""):
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    def set_setting(self, key, value):
        self.execute(
            "INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )

    def event(self, kind, title, detail="", channel_id=None, message_id=None):
        self.execute(
            "INSERT OR IGNORE INTO events(created_at,kind,title,detail,channel_id,message_id) VALUES (?,?,?,?,?,?)",
            (now(), kind, title, detail, channel_id, message_id),
        )

    def backup(self, destination: Path):
        if destination.resolve() == self.path.resolve():
            from .models import DomainError

            raise DomainError("Choisissez un autre fichier que la base active.")
        target = sqlite3.connect(destination)
        try:
            with self.connect() as source:
                source.backup(target)
        finally:
            target.close()
        destination.chmod(0o600)
