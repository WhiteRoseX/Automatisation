"""Browser build checks: no Qt/WebEngine runtime dependency."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / 'telepilot' / 'web'

class WebBundleTests(unittest.TestCase):
    def test_local_web_assets(self):
        html = (WEB / 'index.html').read_text()
        js = (WEB / 'assets/app.js').read_text()
        self.assertIn('assets/polish.css', html)
        self.assertIn('assets/app.js', html)
        self.assertNotIn('qwebchannel', html.lower())
        self.assertIn("fetch('/api/state'", js)
        self.assertIn("fetch('/api/command'", js)
        self.assertIn('function network()', js)
        self.assertIn('function library()', js)

    def test_local_server_not_qt(self):
        main = (ROOT / 'telepilot' / '__main__.py').read_text()
        server = (ROOT / 'telepilot' / 'local_web' / 'server.py').read_text()
        self.assertIn('from .local_web.server import launch', main)
        self.assertNotIn('PySide6', main)
        self.assertIn("('127.0.0.1', port)", server)
        self.assertIn('SameSite=Strict', server)

    def test_no_external_frontend_dependencies(self):
        html = (WEB / 'index.html').read_text()
        self.assertNotIn('https://fonts.', html)
        self.assertNotIn('cdn.jsdelivr', html)
        self.assertNotIn('react', html.lower())

if __name__ == '__main__':
    unittest.main()
