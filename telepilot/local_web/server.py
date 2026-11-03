"""TelePilot local browser server — stdlib HTTP, no Qt and no remote hosting.

Binds only 127.0.0.1 on an ephemeral port; requires a one-time browser session
cookie for every state, command and media request. All Telegram work stays in
ApplicationService's own asyncio loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import webbrowser
from concurrent.futures import TimeoutError as FutureTimeout
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from telepilot.core.models import DomainError, RateLimited
from telepilot.diagnostics import log_exception

LOG = logging.getLogger('telepilot')
ROOT = (Path(__file__).resolve().parent.parent / 'web').resolve()
ASSETS = {'/': ROOT / 'index.html', '/assets/app.js': ROOT / 'assets' / 'app.js',
          '/assets/style.css': ROOT / 'assets' / 'style.css',
          '/assets/polish.css': ROOT / 'assets' / 'polish.css',
          '/assets/studio.css': ROOT / 'assets' / 'studio.css'}
COMMANDS = {
    'sync_channels', 'engine', 'approve_media', 'withdraw', 'favorite', 'publish',
    'cancel', 'pause', 'resolve', 'source', 'channel_notes', 'resolve_channel',
    'network_link', 'network_unlink', 'verify_source', 'browse_channel_media',
    'import_channel_media', 'import_telegram', 'auto_import', 'partner',
    'partner_optout', 'exchange', 'exchange_state', 'exchange_schedule',
    'exchange_verify', 'watch', 'recent', 'settings', 'restore_session',
    'create_community', 'channel_avatar', 'partner_messages', 'partner_reply',
    'configure', 'request_code', 'sign_in', 'logout', 'reset_auth', 'edit_phone',
    'backup', 'open_logs', 'open_media_folder', 'external_link', 'media_thumbnail',
}
MAX_JSON = 1024 * 1024
MAX_UPLOAD = 2 * 1024 ** 3  # streamed to disk; never buffered in RAM


class CoreRunner:
    def __init__(self, service):
        self.service = service
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name='telepilot-core', daemon=True)
        self.ready = threading.Event()
        self._active = False
        self.last_error = ''

    def start(self):
        self.thread.start()
        if not self.ready.wait(timeout=10):
            raise RuntimeError('Le moteur TelePilot ne démarre pas.')
        self.submit('restore_session')  # non-blocking, does not expose credentials

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.engine_task = self.loop.create_task(self.service.engine.run())
        self.watch_task = self.loop.create_task(self._watch())
        self.ready.set()
        self.loop.run_forever()
        pending = asyncio.all_tasks(self.loop)
        for task in pending:
            task.cancel()
        self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self.loop.run_until_complete(self.loop.shutdown_asyncgens())
        self.loop.close()

    async def _watch(self):
        await asyncio.sleep(10)
        while True:
            if self.service.gateway.connected:
                try:
                    await self.service.poll_auto_imports()
                    if self.service.db.setting('auto_watch', '0') == '1':
                        await self.service.command('watch')
                except Exception as exc:
                    log_exception(exc, 'local_web_watch')
            await asyncio.sleep(300)

    async def _command(self, name, args):
        return await self.service.command(name, **args)

    def submit(self, name, args=None):
        return asyncio.run_coroutine_threadsafe(self._command(name, args or {}), self.loop)

    def execute(self, name, args, timeout=90):
        try:
            return self.submit(name, args).result(timeout=timeout)
        except FutureTimeout:
            raise DomainError('Opération toujours en cours. Consultez les tâches avant de réessayer.') from None

    async def _snapshot(self):
        return self.service.snapshot()

    def snapshot(self):
        return asyncio.run_coroutine_threadsafe(self._snapshot(), self.loop).result(timeout=15)

    async def _shutdown(self):
        self.service.engine.enabled = False
        self.service.engine.stopping = True
        self.watch_task.cancel()
        self.engine_task.cancel()
        await asyncio.gather(self.watch_task, self.engine_task, return_exceptions=True)
        try:
            await self.service.gateway.close()
        except Exception as exc:
            log_exception(exc, 'shutdown')
        self.loop.call_later(0.05, self.loop.stop)

    def stop(self):
        if self.thread.is_alive() and self.loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._shutdown(), self.loop)
            try:
                future.result(timeout=8)
            except Exception:
                pass
            self.thread.join(timeout=10)


def safe_error(exc):
    if isinstance(exc, DomainError):
        return str(exc)
    if isinstance(exc, RateLimited):
        return f'Telegram impose une attente de {exc.seconds} secondes.'
    errors = {
        'PhoneCodeInvalidError': 'Code Telegram incorrect.',
        'PhoneCodeExpiredError': 'Code Telegram expiré.',
        'PasswordHashInvalidError': 'Mot de passe 2FA incorrect.',
        'PhoneNumberInvalidError': 'Numéro de téléphone invalide.',
        'FloodWaitError': 'Telegram limite momentanément les requêtes.',
        'ConnectionError': 'La connexion à Telegram est indisponible.',
        'TimeoutError': 'Le délai de réponse Telegram a expiré.',
        'ApiIdInvalidError': 'API ID ou API hash incorrect.',
    }
    return errors.get(type(exc).__name__, f'Opération interrompue ({type(exc).__name__}). Consultez les journaux.')


class LocalHTTP(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address, handler, runner, paths):
        super().__init__(address, handler)
        self.runner = runner
        self.paths = paths
        self.cookie = secrets.token_urlsafe(32)
        self.launch_token = secrets.token_urlsafe(32)


class Handler(BaseHTTPRequestHandler):
    server: LocalHTTP
    protocol_version = 'HTTP/1.1'

    def log_message(self, format, *args):
        # Never log URLs; launch token must never leak into logs.
        return

    def headers_common(self, status, content_type, length, extra=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()

    def write(self, code, content, type='application/json; charset=utf-8', extra=None):
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False, default=str).encode('utf-8')
        elif isinstance(content, str):
            content = content.encode('utf-8')
        self.headers_common(code, type, len(content), extra)
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def valid_host(self):
        host = self.headers.get('Host', '')
        return host == f'127.0.0.1:{self.server.server_port}'

    def authorized(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
        except Exception:
            return False
        item = cookie.get('telepilot_session')
        return bool(item and secrets.compare_digest(item.value, self.server.cookie))

    def origin_valid(self):
        origin = self.headers.get('Origin', '')
        return origin == f'http://127.0.0.1:{self.server.server_port}'

    def do_GET(self):
        if not self.valid_host():
            return self.write(HTTPStatus.FORBIDDEN, {'error': 'Accès non autorisé'})
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == '/launch':
            token = parse_qs(parsed.query).get('token', [''])[0]
            if not secrets.compare_digest(token, self.server.launch_token):
                return self.write(HTTPStatus.FORBIDDEN, {'error': 'Lien de lancement invalide'})
            self.server.launch_token = ''  # the bootstrap link is single-use
            self.send_response(HTTPStatus.FOUND)
            self.send_header('Location', '/')
            self.send_header('Set-Cookie', f'telepilot_session={self.server.cookie}; HttpOnly; SameSite=Strict; Path=/')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if not self.authorized():
            return self.write(HTTPStatus.FORBIDDEN, {'error': 'Session navigateur non autorisée. Ouvrez TelePilot depuis le Terminal.'})
        if path in ASSETS:
            file = ASSETS[path]
            if not file.is_file():
                return self.write(404, {'error': 'Fichier absent'})
            content_type = 'text/html; charset=utf-8' if path == '/' else 'text/css; charset=utf-8' if path.endswith('.css') else 'text/javascript; charset=utf-8'
            return self.write(200, file.read_bytes(), content_type)
        if path == '/api/state':
            try:
                return self.write(200, self.server.runner.snapshot())
            except Exception as exc:
                log_exception(exc, 'http_snapshot')
                return self.write(500, {'error': 'Impossible de récupérer les données.'})
        if path.startswith('/api/avatar/'):
            try:
                channel_id = int(path.rsplit('/', 1)[-1])
                channels = self.server.runner.snapshot().get('channels', [])
                if not any(c['id'] == channel_id for c in channels):
                    return self.write(404, {'error': 'Canal inconnu'})
                directory = self.server.paths.media / 'avatars'
                photo = directory / f'{channel_id}.jpg'
                missing = directory / f'{channel_id}.none'
                if not photo.is_file() and not missing.is_file():
                    self.server.runner.execute('channel_avatar', {'channel_id': channel_id}, timeout=18)
                    if not photo.is_file():
                        directory.mkdir(parents=True, exist_ok=True)
                        missing.touch()
                if not photo.is_file() or photo.stat().st_size > 2 * 1024 * 1024:
                    return self.write(404, {'error': 'Photo absente'})
                return self.write(200, photo.read_bytes(), 'image/jpeg')
            except Exception as exc:
                log_exception(exc, 'avatar_preview')
                return self.write(404, {'error': 'Photo indisponible'})
        if path.startswith('/api/media/'):
            try:
                media_id = int(path.rsplit('/', 1)[-1])
                data = self.server.runner.snapshot()
                media = next((m for m in data.get('media', []) if m['id'] == media_id), None)
                if not media or media.get('revoked') or media.get('kind') not in ('photo', 'video'):
                    return self.write(404, {'error': 'Média indisponible'})
                target = Path(media['path']).resolve()
                if not target.is_relative_to(self.server.paths.media.resolve()) or not target.is_file():
                    return self.write(404, {'error': 'Fichier absent'})
                mime = mimetypes.guess_type(target)[0]
                images = {'image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/avif'}
                videos = {'video/mp4', 'video/webm', 'video/quicktime', 'video/x-m4v'}
                if mime not in images | videos:
                    return self.write(415, {'error': 'Format non supporté'})
                size = target.stat().st_size
                if mime in images and size > 24 * 1024 * 1024:
                    return self.write(413, {'error': 'Image trop volumineuse'})
                if mime in images:
                    return self.write(200, target.read_bytes(), mime)
                # Stream only the requested byte range, never buffer a large video.
                range_value = self.headers.get('Range', '')
                start, end = 0, size - 1
                if range_value:
                    import re
                    match = re.fullmatch(r'bytes=(\d+)-(\d*)', range_value)
                    if not match:
                        return self.write(416, {'error': 'Plage invalide'})
                    start = int(match.group(1))
                    end = min(size - 1, int(match.group(2))) if match.group(2) else min(size - 1, start + 2*1024*1024 - 1)
                    if start >= size or end < start:
                        return self.write(416, {'error': 'Plage invalide'})
                else:
                    end = min(size - 1, 2*1024*1024 - 1)
                length = end - start + 1
                code = 206 if range_value or end < size - 1 else 200
                extra = {'Accept-Ranges': 'bytes', 'Content-Range': f'bytes {start}-{end}/{size}'} if code == 206 else {'Accept-Ranges': 'bytes'}
                self.headers_common(code, mime, length, extra)
                with target.open('rb') as video:
                    video.seek(start)
                    remaining = length
                    while remaining:
                        block = video.read(min(65536, remaining))
                        if not block:
                            break
                        self.wfile.write(block)
                        remaining -= len(block)
                return
            except (ValueError, OSError, BrokenPipeError, ConnectionResetError):
                return
        if path == '/favicon.ico':
            return self.write(204, b'')
        self.write(404, {'error': 'Ressource inconnue'})

    def _open_folder(self, path):
        # macOS Finder integration; does not execute shell text from requests.
        if os.name == 'posix' and __import__('sys').platform == 'darwin':
            subprocess.Popen(['open', str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            webbrowser.open(Path(path).as_uri())

    def do_POST(self):
        if not self.valid_host() or not self.authorized() or not self.origin_valid() or self.headers.get('X-TelePilot-Request') != '1':
            return self.write(HTTPStatus.FORBIDDEN, {'error': 'Requête interdite'})
        path = urlsplit(self.path).path
        if path == '/api/command':
            length = int(self.headers.get('Content-Length', 0))
            if length < 1 or length > MAX_JSON:
                return self.write(413, {'error': 'Requête trop volumineuse'})
            try:
                req = json.loads(self.rfile.read(length))
                name, args = req.get('name'), req.get('args', {})
                if name not in COMMANDS or not isinstance(args, dict):
                    return self.write(400, {'name': name, 'ok': False, 'data': 'Commande non autorisée'})
                if name == 'media_thumbnail':
                    media_id = int(args.get('media_id'))
                    snap = self.server.runner.snapshot()
                    media = next((m for m in snap.get('media', []) if m['id'] == media_id), None)
                    image = f'/api/media/{media_id}' if (media and media.get('kind') in ('photo','video') and not media.get('revoked')) else None
                    result = {'media_id': media_id, 'image': image}
                elif name == 'backup':
                    from datetime import datetime
                    backup_dir = self.server.paths.root / 'backups'
                    backup_dir.mkdir(mode=0o700, exist_ok=True)
                    dest = backup_dir / f'telepilot-{datetime.now():%Y%m%d-%H%M%S}.sqlite3'
                    result = self.server.runner.execute('backup', {'path': str(dest)}) + f' Fichier : {dest}'
                elif name == 'open_logs':
                    self._open_folder(self.server.paths.logs)
                    result = 'Journaux ouverts'
                elif name == 'open_media_folder':
                    media_id = int(args.get('media_id'))
                    snap = self.server.runner.snapshot()
                    media = next((m for m in snap.get('media', []) if m['id'] == media_id), None)
                    if not media:
                        raise DomainError('Média introuvable')
                    target = Path(media['path']).resolve()
                    if not target.is_relative_to(self.server.paths.media.resolve()) or not target.is_file():
                        raise DomainError('Fichier local indisponible')
                    self._open_folder(target.parent)
                    result = 'Dossier ouvert'
                elif name == 'external_link':
                    from urllib.parse import urlparse
                    url = str(args.get('url', ''))
                    parsed = urlparse(url)
                    if parsed.scheme != 'https' or parsed.hostname not in {'t.me', 'telegram.me', 'my.telegram.org'}:
                        raise DomainError('Lien non autorisé')
                    webbrowser.open(url)
                    result = 'Lien ouvert'
                else:
                    result = self.server.runner.execute(name, args)
                return self.write(200, {'name': name, 'ok': True, 'data': result})
            except Exception as exc:
                log_exception(exc, 'http_command')
                return self.write(200, {'name': locals().get('name'), 'ok': False, 'data': safe_error(exc)})
        if path == '/api/upload':
            length = int(self.headers.get('Content-Length', 0))
            if length < 1 or length > MAX_UPLOAD:
                return self.write(413, {'error': 'Taille de fichier refusée'})
            fname = unquote(self.headers.get('X-File-Name', 'media.bin'))
            fname = Path(fname).name[:160]
            if not fname or fname in ('.', '..') or '/' in fname or '\\' in fname:
                return self.write(400, {'error': 'Nom de fichier invalide'})
            tempdir = Path(tempfile.mkdtemp(prefix='telepilot-upload-', dir=str(self.server.paths.root)))
            dest = tempdir / fname
            try:
                with dest.open('wb') as output:
                    remaining = length
                    while remaining:
                        block = self.rfile.read(min(1024 * 1024, remaining))
                        if not block:
                            raise ConnectionError('Téléchargement interrompu')
                        output.write(block)
                        remaining -= len(block)
                result = self.server.runner.execute('import_local', {'paths': [str(dest)], 'rights': 'unverified', 'evidence': '', 'sensitive': True, 'reviewed': False, 'caption': ''}, timeout=300)
                return self.write(200, {'ok': True, 'data': result})
            except Exception as exc:
                log_exception(exc, 'http_upload')
                return self.write(200, {'ok': False, 'data': safe_error(exc)})
            finally:
                shutil.rmtree(tempdir, ignore_errors=True)
        self.write(404, {'error': 'Commande inconnue'})


def launch(service, paths, no_browser=False, port=0):
    """Serve TelePilot exclusively on 127.0.0.1. Ctrl+C cleanly stops it."""
    runner = CoreRunner(service)
    runner.start()
    server = LocalHTTP(('127.0.0.1', port), Handler, runner, paths)
    login_url = f'http://127.0.0.1:{server.server_port}/launch?token={server.launch_token}'
    print(f'\n  TelePilot local : http://127.0.0.1:{server.server_port}/')
    print('  Le navigateur va s’ouvrir automatiquement. Ctrl+C pour arrêter.\n')
    if not no_browser:
        webbrowser.open(login_url)
    else:
        # For headless tests this is intentionally printed only on request.
        print('  URL de lancement :', login_url)
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print('\nFermeture de TelePilot…')
    finally:
        server.server_close()
        runner.stop()
    return 0
