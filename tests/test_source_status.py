"""Source status: one-click revalidation without confusing permissions and access."""
import tempfile
import unittest
from pathlib import Path

from telepilot.config import Paths
from telepilot.core.models import now
from telepilot.service import ApplicationService


class ConnectedGateway:
    connected = True
    identity = "Faux compte"


class SourceStatusTests(unittest.TestCase):
    def test_stale_access_check_does_not_disable_download_button(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = Paths(Path(directory))
            paths.prepare()
            service = ApplicationService(paths, ConnectedGateway(), demo=True)
            service.db.execute("""INSERT INTO channels(id,title,role,protected)
                VALUES (42,'Canal autorisé','owner',0)""")
            service.db.execute("""INSERT INTO sources(channel_id,title,rights,evidence)
                VALUES (42,'Canal autorisé','own','Contenu personnel documenté')""")
            source = service.snapshot()["sources"][0]
            self.assertFalse(source["downloadable"])
            self.assertTrue(source["can_attempt_download"])
            self.assertIn("automatiquement", source["download_reason"])

            service.db.execute("UPDATE sources SET download_checked_at=? WHERE channel_id=42", (now(),))
            source = service.snapshot()["sources"][0]
            self.assertTrue(source["downloadable"])
            self.assertTrue(source["can_attempt_download"])

            service.db.execute("UPDATE channels SET protected=1 WHERE id=42")
            source = service.snapshot()["sources"][0]
            self.assertFalse(source["downloadable"])
            self.assertFalse(source["can_attempt_download"])

    def test_missing_permission_never_enables_download(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = Paths(Path(directory))
            paths.prepare()
            service = ApplicationService(paths, ConnectedGateway(), demo=True)
            service.db.execute("INSERT INTO channels(id,title,role) VALUES (50,'Canal','member')")
            service.db.execute("""INSERT INTO sources(channel_id,title,rights,evidence)
                VALUES (50,'Canal','unverified','')""")
            source = service.snapshot()["sources"][0]
            self.assertFalse(source["downloadable"])
            self.assertFalse(source["can_attempt_download"])
