"""Launch TelePilot as a local web application in the default browser."""
import argparse
import fcntl
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import Paths


def main():
    parser = argparse.ArgumentParser(description='TelePilot — tableau de bord local dans votre navigateur')
    parser.add_argument('--data-dir', type=Path, help='Dossier des données locales (session, médias, SQLite)')
    parser.add_argument('--no-browser', action='store_true', help='Démarrer sans ouvrir le navigateur')
    parser.add_argument('--port', type=int, default=0, help='Port local (0 = port libre automatique)')
    parser.add_argument('--live', action='store_true', help='Option historique compatible avec les anciens lanceurs')
    args = parser.parse_args()
    root = (args.data_dir or Path(__file__).resolve().parent.parent / '.telepilot').expanduser().resolve()
    paths = Paths(root / 'live')
    paths.prepare()
    lock = (paths.root / 'instance.lock').open('a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('TelePilot est déjà lancé pour cet espace de données.', file=sys.stderr)
        return 1
    handler = RotatingFileHandler(paths.logs / 'telepilot.log', maxBytes=1_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger = logging.getLogger('telepilot')
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logging.getLogger('telethon').addHandler(logging.NullHandler())
    logging.getLogger('telethon').propagate = False

    from .service import ApplicationService
    from .telegram.client import TelethonGateway
    from .local_web.server import launch
    gateway = TelethonGateway(paths.sessions / 'account')
    service = ApplicationService(paths, gateway, False)
    try:
        return launch(service, paths, no_browser=args.no_browser, port=args.port)
    finally:
        lock.close()
        logger.info('TelePilot local stopped')


if __name__ == '__main__':
    raise SystemExit(main())
