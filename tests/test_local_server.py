"""HTTP security/integration checks with no real Telegram account."""
import http.cookiejar
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPCookieProcessor, Request

from telepilot.config import Paths
from telepilot.local_web.server import Handler, LocalHTTP

class FakeRunner:
    def snapshot(self):
        return {'channels': [], 'media': [], 'connected': False, 'blur': True}
    def execute(self, name, args):
        if name == 'sync_channels':
            return 'OK'
        raise ValueError('Fake request')

class LocalServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        paths = Paths(Path(self.tmp.name))
        paths.prepare()
        self.server = LocalHTTP(('127.0.0.1', 0), Handler, FakeRunner(), paths)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def test_browser_launch_and_state(self):
        with self.assertRaises(HTTPError) as error:
            self.opener.open(self.base + '/api/state')
        self.assertEqual(error.exception.code, 403)
        self.opener.open(self.base + '/launch?token=' + self.server.launch_token)
        state = json.load(self.opener.open(self.base + '/api/state'))
        self.assertEqual(state['channels'], [])
        html = self.opener.open(self.base + '/').read().decode()
        self.assertIn('assets/app.js', html)
        css = self.opener.open(self.base + '/assets/polish.css').read().decode()
        self.assertIn('backdrop-filter', css)

    def test_bad_csrf_rejected(self):
        self.opener.open(self.base + '/launch?token=' + self.server.launch_token)
        data = json.dumps({'name': 'sync_channels', 'args': {}}).encode()
        bad = Request(self.base + '/api/command', data, headers={'Content-Type':'application/json'}, method='POST')
        with self.assertRaises(HTTPError) as error:
            self.opener.open(bad)
        self.assertEqual(error.exception.code, 403)
        valid = Request(self.base + '/api/command', data, headers={'Content-Type':'application/json', 'Origin': self.base, 'X-TelePilot-Request':'1'}, method='POST')
        response = json.load(self.opener.open(valid))
        self.assertEqual(response['data'], 'OK')

    def test_disallowed_command_rejected(self):
        self.opener.open(self.base + '/launch?token=' + self.server.launch_token)
        data = json.dumps({'name': '__dict__', 'args': {}}).encode()
        request = Request(self.base + '/api/command', data, headers={'Content-Type':'application/json', 'Origin': self.base, 'X-TelePilot-Request':'1'}, method='POST')
        with self.assertRaises(HTTPError) as error:
            self.opener.open(request)
        self.assertEqual(error.exception.code, 400)
