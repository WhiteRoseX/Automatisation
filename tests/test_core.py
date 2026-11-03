import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from telepilot.core.database import Database
from telepilot.core.media import MediaLibrary
from telepilot.core.tasks import TaskQueue
from telepilot.core.engine import Engine
from telepilot.core.importer import Importer
from telepilot.core.partners import Partners
from telepilot.core.monitor import Monitor
from telepilot.core.models import DomainError, RateLimited, Rejected, now


class Fixture:
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.root=Path(self.temporary.name)
        self.db=Database(self.root/"app.sqlite3")
        self.library=MediaLibrary(self.db,self.root/"media")
        self.queue=TaskQueue(self.db,self.library)
        self.db.execute("INSERT INTO channels(id,title,can_post) VALUES (1,'Mon canal',1)")
        self.db.execute("INSERT INTO channels(id,title,can_post) VALUES (2,'Partenaire',0)")

    def tearDown(self):self.temporary.cleanup()

    def media(self,content=b"fixture",**kwargs):
        path=self.root/"source.jpg";path.write_bytes(content)
        return self.library.import_file(path,**kwargs)

    def approved(self,**kwargs):
        return self.media(rights="own",evidence="Attestation personnelle",reviewed=True,**kwargs)

    def task(self,**kwargs):return self.queue.publication(1,"Texte validé",draft=False,**kwargs)
    def record(self,task_id):return self.db.one("SELECT * FROM tasks WHERE id=?",(task_id,))


class StorageTests(Fixture,unittest.TestCase):
    def test_content_hash_deduplicates_renamed_files_without_promoting_rights(self):
        first=self.media()
        other=self.root/"renamed.png";other.write_bytes(b"fixture")
        second=self.library.import_file(other,rights="own",evidence="mine",reviewed=True)
        self.assertEqual(first,second)
        self.assertEqual(len(self.db.rows("SELECT * FROM media")),1)
        with self.assertRaises(DomainError):self.library.require_publishable([first])

    def test_approval_requires_documented_human_review(self):
        for evidence,reviewed in (("",True),("preuve",False)):
            with self.assertRaises(DomainError):self.media(rights="partner",evidence=evidence,reviewed=reviewed)

    def test_unverified_can_be_drafted_but_not_queued(self):
        mid=self.media()
        self.queue.publication(1,"Brouillon",[mid],draft=True)
        with self.assertRaises(DomainError):self.task(media_ids=[mid])

    def test_withdrawal_cancels_pending_but_preserves_history(self):
        mid=self.approved();tid=self.task(media_ids=[mid])
        self.library.withdraw(mid,delete_file=True)
        self.assertEqual(self.record(tid)["state"],"cancelled")
        row=self.db.one("SELECT * FROM media WHERE id=?",(mid,))
        self.assertFalse(Path(row["path"]).exists())
        self.assertTrue(row["revoked"])
        with self.assertRaises(DomainError):self.library.approve(mid,"own","preuve",True,False,"")

    def test_source_revocation_blocks_already_approved_media(self):
        sid=self.db.execute("INSERT INTO sources(channel_id,title,rights,evidence) VALUES (2,'Source','partner','Accord')")
        mid=self.approved(source_id=sid,message_id=10)
        self.db.execute("UPDATE sources SET rights='forbidden' WHERE id=?",(sid,))
        with self.assertRaises(DomainError):self.task(media_ids=[mid])

    def test_protected_source_refuses_import(self):
        sid=self.db.execute("INSERT INTO sources(channel_id,title,rights,evidence) VALUES (2,'Source','partner','Accord')")
        self.db.execute("UPDATE channels SET protected=1 WHERE id=2")
        with self.assertRaises(DomainError):self.media(source_id=sid,message_id=1)

    def test_repeat_requires_explicit_override(self):
        mid=self.approved();self.task(media_ids=[mid])
        with self.assertRaises(DomainError):self.task(media_ids=[mid])
        self.task(media_ids=[mid],allow_repeat=True)

    def test_backup_is_consistent_and_private(self):
        self.task();path=self.root/"backup.sqlite3";self.db.backup(path)
        copy=Database(path)
        self.assertEqual(len(copy.rows("SELECT * FROM tasks")),1)
        self.assertEqual(path.stat().st_mode&0o777,0o600)

    def test_future_database_version_is_not_overwritten(self):
        self.db.execute("PRAGMA user_version=99")
        with self.assertRaises(RuntimeError):Database(self.db.path)

    def test_atomic_claim_has_one_winner(self):
        self.task()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(lambda _:self.queue.claim(),range(2)))
        self.assertEqual(sum(r is not None for r in results),1)

    def test_recovery_never_blindly_retries_publish(self):
        tid=self.task();self.queue.claim();TaskQueue(Database(self.db.path),self.library).recover()
        self.assertEqual(self.record(tid)["state"],"unknown")
        self.assertIsNone(self.queue.claim())

    def test_utf16_caption_and_album_limits(self):
        mid=self.approved()
        with self.assertRaises(DomainError):self.queue.publication(1,"😀"*513,[mid],draft=False)
        with self.assertRaises(DomainError):self.queue.publication(1,"text",list(range(11)),draft=True)


class FakeGateway:
    connected=True
    identity="Test"
    def __init__(self):self.sent=[];self.failure=None;self.preflight=None;self.allowed=True;self.messages=[]
    async def check_destination(self,channel_id):
        if self.preflight:self.preflight()
        return self.allowed
    async def publish(self,channel_id,text,paths,random_id):
        self.sent.append(random_id)
        if self.failure:raise self.failure
        return [42]
    async def recent(self,channel_id,limit=30):return self.messages


class EngineTests(Fixture,unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.gateway=FakeGateway();self.engine=Engine(self.db,self.queue,self.gateway);self.engine.enabled=True

    async def test_success_records_remote_ids(self):
        tid=self.task();await self.engine.tick()
        self.assertEqual(self.record(tid)["state"],"completed")
        self.assertEqual(json.loads(self.record(tid)["result"]),[42])

    async def test_timeout_after_send_is_unknown_and_never_retried(self):
        tid=self.task();self.gateway.failure=TimeoutError("secret content")
        await self.engine.tick();await self.engine.tick()
        self.assertEqual(self.record(tid)["state"],"unknown")
        self.assertEqual(len(self.gateway.sent),1)
        self.assertNotIn("secret",self.record(tid)["error"])

    async def test_flood_wait_is_persistent_and_honored(self):
        tid=self.task();self.gateway.failure=RateLimited(800)
        await self.engine.tick()
        row=self.record(tid)
        self.assertEqual(row["state"],"scheduled")
        self.assertGreater(row["due_at"],now()+790)
        self.assertGreater(float(self.db.setting("flood_until")),now()+790)

    async def test_preflight_network_error_can_retry_without_unknown(self):
        tid=self.task()
        def fail():raise ConnectionError()
        self.gateway.preflight=fail;await self.engine.tick()
        self.assertEqual(self.record(tid)["state"],"scheduled")
        self.assertEqual(self.gateway.sent,[])

    async def test_timeout_before_send_is_retryable_not_file_failure(self):
        tid=self.task()
        self.gateway.preflight=lambda: (_ for _ in ()).throw(TimeoutError("secret"))
        await self.engine.tick()
        self.assertEqual(self.record(tid)["state"], "scheduled")
        self.assertEqual(self.gateway.sent, [])
        self.assertNotIn("secret", self.record(tid)["error"])

    async def test_missing_local_file_fails_without_retry(self):
        tid=self.task()
        self.gateway.preflight=lambda: (_ for _ in ()).throw(FileNotFoundError(2, "missing file", "/private/file"))
        await self.engine.tick()
        self.assertEqual(self.record(tid)["state"], "failed")
        self.assertEqual(self.gateway.sent, [])
        self.assertNotIn("/private", self.record(tid)["error"])

    async def test_rights_revoked_during_network_preflight_prevent_send(self):
        mid=self.approved();tid=self.task(media_ids=[mid])
        self.gateway.preflight=lambda:self.library.withdraw(mid)
        await self.engine.tick()
        self.assertEqual(self.record(tid)["state"],"failed")
        self.assertEqual(self.gateway.sent,[])

    async def test_permission_loss_prevents_send(self):
        tid=self.task();self.gateway.allowed=False;await self.engine.tick()
        self.assertEqual(self.record(tid)["state"],"failed")
        self.assertEqual(self.gateway.sent,[])

    async def test_minimum_spacing_survives_engine_restart(self):
        first=self.task();second=self.task();await self.engine.tick()
        engine=Engine(self.db,self.queue,self.gateway);engine.enabled=True;await engine.tick()
        self.assertEqual(len(self.gateway.sent),1)
        self.assertEqual(self.record(first)["state"],"completed")
        self.assertEqual(self.record(second)["state"],"scheduled")

    async def test_pending_task_is_not_sent_when_engine_disabled(self):
        tid=self.task();self.engine.enabled=False;await self.engine.tick()
        self.assertEqual(self.record(tid)["state"],"pending")
        self.assertEqual(self.gateway.sent,[])

    async def test_explicit_rpc_rejection_is_failed_not_unknown(self):
        tid=self.task();self.gateway.failure=Rejected("Refus Telegram");await self.engine.tick()
        self.assertEqual(self.record(tid)["state"],"failed")


class ImportTests(Fixture,unittest.IsolatedAsyncioTestCase):
    async def test_import_restart_deduplicates_downloads_and_preserves_album(self):
        sid=self.db.execute("INSERT INTO sources(channel_id,title,rights,evidence) VALUES (2,'Source','partner','Accord')")
        downloads=[];root=self.root
        class Gateway:
            connected=True
            async def import_batch(self,channel,cursor,start,end,limit):
                return [{"id":1,"date":now()-10,"kind":"photo","protected":False,"media_id":"123","album_id":"456","text":"Légende"}] if not cursor else []
            async def download(self,channel,message,directory):
                downloads.append(message);path=directory/"file.jpg";path.write_bytes(b"photo");return str(path)
        gateway=Gateway();importer=Importer(self.db,self.library,self.queue,gateway)
        engine=Engine(self.db,self.queue,gateway,importer);engine.enabled=True
        tid=importer.create(sid,now()-100,now()+100,1)
        await engine.tick()
        self.assertEqual(self.record(tid)["state"],"completed")
        self.assertEqual(self.db.one("SELECT album_id FROM provenance")["album_id"],"456")
        importer.create(sid,now()-100,now()+100,1);await engine.tick()
        self.assertEqual(downloads,[1])
        self.assertEqual(self.db.one("SELECT rights FROM media")["rights"],"unverified")

    async def test_paused_import_can_resume_and_cancel(self):
        sid=self.db.execute("INSERT INTO sources(channel_id,title,rights,evidence) VALUES (2,'Source','partner','Accord')")
        importer=Importer(self.db,self.library,self.queue,None)
        tid=importer.create(sid,now()-100,now(),10);self.queue.pause(tid)
        self.assertIsNone(self.queue.claim());self.queue.pause(tid)
        self.assertEqual(self.queue.claim()["id"],tid);self.queue.cancel(tid)
        self.assertEqual(self.record(tid)["state"],"cancelled")


class PartnershipTests(Fixture,unittest.IsolatedAsyncioTestCase):
    def create_exchange(self):
        partners=Partners(self.db,self.queue)
        pid=partners.save("Partenaire",channel_id=2)
        eid=partners.exchange(pid,1,"Échange","Mon annonce","Son annonce",now()+100,24,"Accord écrit")
        return partners,eid

    async def test_exchange_requires_explicit_agreement(self):
        partners,eid=self.create_exchange()
        with self.assertRaises(DomainError):partners.schedule(eid)
        partners.set_state(eid,"Accord conclu");partners.schedule(eid)
        with self.assertRaises(DomainError):partners.schedule(eid)
        self.assertEqual(len(self.db.rows("SELECT * FROM tasks")),1)

    async def test_recovery_between_task_insert_and_exchange_link_is_idempotent(self):
        partners,eid=self.create_exchange();partners.set_state(eid,"Accord conclu")
        self.queue.publication(1,"Mon annonce",draft=False,task_id=f"exchange_{eid}")
        partners.schedule(eid)
        self.assertEqual(len(self.db.rows("SELECT * FROM tasks")),1)

    async def test_cancelled_agreement_cancels_unsent_advertisement(self):
        partners,eid=self.create_exchange();partners.set_state(eid,"Accord conclu");tid=partners.schedule(eid)
        partners.set_state(eid,"Annulé")
        self.assertEqual(self.record(tid)["state"],"cancelled")

    async def test_observation_does_not_infer_deletion(self):
        sid=self.db.execute("INSERT INTO sources(channel_id,title,rights,evidence,watch) VALUES (2,'Source','partner','Accord',1)")
        gateway=FakeGateway();monitor=Monitor(self.db,gateway)
        gateway.messages=[dict(id=1,text="Message",date=now(),views=None,forwards=None,reactions=None,kind="text")]
        await monitor.sync(sid);gateway.messages=[];await monitor.sync(sid)
        self.assertEqual(len(self.db.rows("SELECT * FROM observations")),1)
        self.assertEqual(len(self.db.rows("SELECT * FROM events WHERE kind='deleted'")),0)


if __name__=="__main__":unittest.main()

