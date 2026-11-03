"""Version 0.6 integration tests: real local preview routes and explicit Telegram actions."""
import asyncio
import http.cookiejar
import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from telethon import types
from telepilot.config import Paths
from telepilot.core.models import Channel, DomainError
from telepilot.local_web.server import Handler, LocalHTTP
from telepilot.service import ApplicationService
from telepilot.telegram.client import TelethonGateway


class MockGateway:
    connected = True
    identity = 'Test'

    async def create_community(self, title, about, kind):
        return Channel(-10022, title, can_post=True, entity_type='broadcast', role='owner')

    async def partner_messages(self, handle):
        return [{'id': 6, 'text': 'Bonjour', 'out': False, 'date': 1720000000}]

    async def reply_to_partner(self, handle, text):
        return 7


class NewCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        paths = Paths(Path(self.tmp.name))
        paths.prepare()
        self.service = ApplicationService(paths, MockGateway(), False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_channel_and_save_to_network(self):
        response = asyncio.run(self.service.command('create_community', title='Notre canal', kind='channel'))
        self.assertEqual(response['id'], -10022)
        row = self.service.db.one('SELECT * FROM channels WHERE id=?', (-10022,))
        self.assertEqual(row['title'], 'Notre canal')
        self.assertEqual(row['role'], 'owner')

    def test_read_and_send_partner_reply(self):
        self.service.db.execute("INSERT INTO partners(name,handle) VALUES('Studio','@studio')")
        messages = asyncio.run(self.service.command('partner_messages', partner_id=1))
        self.assertEqual(messages[0]['text'], 'Bonjour')
        result = asyncio.run(self.service.command('partner_reply', partner_id=1, text='Merci pour votre message'))
        self.assertEqual(result['message_id'], 7)
        self.service.db.execute('UPDATE partners SET opted_out=1 WHERE id=1')
        with self.assertRaises(DomainError):
            asyncio.run(self.service.command('partner_reply', partner_id=1, text='Hello'))

    def test_gateway_create_channel_api_arguments(self):
        gw = TelethonGateway(Path(self.tmp.name) / 'test')
        channel = types.Channel(id=55, title='Test', photo=types.ChatPhotoEmpty(), date=datetime.now(timezone.utc), broadcast=True, creator=True)
        observed = []
        async def fake_send(request):
            observed.append(request)
            return SimpleNamespace(chats=[channel])
        gw.client = fake_send
        gw.connected = True
        result = asyncio.run(gw.create_community('Test', kind='channel'))
        self.assertTrue(observed[0].broadcast)
        self.assertFalse(observed[0].megagroup)
        self.assertEqual(result.role, 'owner')
        self.assertTrue(result.can_post)


class PreviewRunner:
    def __init__(self, media): self.media=media
    def snapshot(self):
        return {'channels':[{'id':88}], 'media':self.media, 'connected':True, 'blur':True}
    def execute(self, name, args, timeout=90):return None


class LocalMediaPreview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.paths = Paths(Path(self.temp.name));self.paths.prepare()
        self.photo = self.paths.media/'example.jpg';self.photo.write_bytes(b'\xff\xd8\xff\xe0demo')
        self.video = self.paths.media/'clip.mp4';self.video.write_bytes(b'0'*1000)
        rows=[{'id':1,'kind':'photo','path':str(self.photo),'sensitive':True,'revoked':False},
              {'id':2,'kind':'video','path':str(self.video),'sensitive':True,'revoked':False}]
        self.server=LocalHTTP(('127.0.0.1',0),Handler,PreviewRunner(rows),self.paths)
        self.thread=threading.Thread(target=self.server.serve_forever, daemon=True);self.thread.start()
        self.opener=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.base=f'http://127.0.0.1:{self.server.server_port}'
        self.opener.open(self.base+'/launch?token='+self.server.launch_token)

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=2);self.temp.cleanup()

    def test_sensitive_image_is_blurred_in_browser_not_replaced_by_placeholder(self):
        r=self.opener.open(self.base+'/api/media/1')
        self.assertEqual(r.headers['Content-Type'],'image/jpeg')
        self.assertEqual(r.read(),self.photo.read_bytes())

    def test_existing_channel_avatar_is_served_from_local_cache(self):
        avatar_dir=self.paths.media/'avatars';avatar_dir.mkdir()
        photo=avatar_dir/'88.jpg';photo.write_bytes(self.photo.read_bytes())
        r=self.opener.open(self.base+'/api/avatar/88')
        self.assertEqual(r.headers['Content-Type'],'image/jpeg')
        self.assertEqual(r.read(),photo.read_bytes())

    def test_video_range_is_streamed(self):
        r=self.opener.open(Request(self.base+'/api/media/2',headers={'Range':'bytes=0-49'}))
        self.assertEqual(r.status,206)
        self.assertEqual(r.headers['Content-Range'],'bytes 0-49/1000')
        self.assertEqual(len(r.read()),50)

    def test_public_request_without_browser_session_fails(self):
        other=build_opener()
        with self.assertRaises(HTTPError) as ctx:other.open(self.base+'/api/media/1')
        self.assertEqual(ctx.exception.code,403)
