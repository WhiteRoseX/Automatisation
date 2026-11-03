from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def database(self): return self.root / "telepilot.sqlite3"
    @property
    def media(self): return self.root / "media"
    @property
    def sessions(self): return self.root / "sessions"
    @property
    def logs(self): return self.root / "logs"

    def prepare(self):
        os.umask(0o077)
        for path in (self.root, self.media, self.sessions, self.logs):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.chmod(0o700)

