"""Content-addressed local storage and explicit provenance/rights review."""
import hashlib
import os
from pathlib import Path
import tempfile
from .database import Database
from .models import ALLOWED_RIGHTS, DomainError, Rights, now

EXTENSIONS = {".jpg": "photo", ".jpeg": "photo", ".png": "photo", ".webp": "photo", ".heic": "photo", ".mp4": "video", ".mov": "video", ".m4v": "video", ".webm": "video"}


class MediaLibrary:
    def __init__(self, db: Database, directory: Path):
        self.db, self.directory = db, directory
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def import_file(self, path, *, rights="unverified", evidence="", sensitive=True,
                    reviewed=False, source_id=None, message_id=None, telegram_media_id=None,
                    album_id=None, caption="", message_date=None):
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix not in EXTENSIONS or not path.is_file():
            raise DomainError("Format non pris en charge. Choisissez une photo ou une vidéo.")
        if rights not in Rights:
            raise DomainError("Statut de droits invalide.")
        if rights in ALLOWED_RIGHTS and (not evidence.strip() or not reviewed):
            raise DomainError("Documentez les droits et confirmez la revue humaine avant d'approuver.")
        if source_id is not None:
            source = self.db.one("SELECT s.*,c.protected FROM sources s LEFT JOIN channels c ON c.id=s.channel_id WHERE s.id=?", (source_id,))
            # Permission to retain a local copy is distinct from a licence to republish.
            download_consent = bool(source and (source["evidence"] or "").startswith("download-confirmed:"))
            if not source or source["protected"] or not (
                (source["rights"] in ALLOWED_RIGHTS and source["evidence"].strip()) or download_consent
            ):
                raise DomainError("Cette source n'autorise pas l'importation.")
        # Hash while copying: the digest describes exactly the stored bytes (no TOCTOU).
        digest = hashlib.sha256()
        fd, temporary = tempfile.mkstemp(dir=self.directory, prefix=".import-")
        try:
            size = 0
            with os.fdopen(fd, "wb") as target, path.open("rb") as source_file:
                while chunk := source_file.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            if not size:
                raise DomainError("Le fichier est vide.")
            sha = digest.hexdigest()
            existing = self.db.one("SELECT * FROM media WHERE sha256=?", (sha,))
            destination = self.directory / (sha + suffix)
            if existing:
                media_id = existing["id"]
                # Re-import does not promote rights or undo a withdrawal.
                if not Path(existing["path"]).exists() and not existing["revoked"]:
                    os.replace(temporary, existing["path"])
            else:
                os.replace(temporary, destination)
                self.db.execute("""INSERT OR IGNORE INTO media(sha256,path,name,kind,size,caption,rights,evidence,sensitive,reviewed,created_at)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (sha, str(destination), path.name, EXTENSIONS[suffix], size,
                     caption, rights, evidence.strip(), int(sensitive), int(reviewed), now()))
                media_id = self.db.one("SELECT id FROM media WHERE sha256=?", (sha,))["id"]
            if source_id is not None:
                self.db.execute("INSERT OR IGNORE INTO provenance(media_id,source_id,message_id,telegram_media_id,album_id,message_date) VALUES (?,?,?,?,?,?)",
                                (media_id, source_id, message_id, telegram_media_id, album_id, message_date))
            self.db.event("media", "Média ajouté" if not existing else "Doublon reconnu", f"Média #{media_id}")
            return media_id
        finally:
            Path(temporary).unlink(missing_ok=True)

    def approve(self, media_id, rights, evidence, reviewed, sensitive, caption):
        if rights not in Rights:
            raise DomainError("Statut invalide.")
        if rights in ALLOWED_RIGHTS and (not evidence.strip() or not reviewed):
            raise DomainError("Une preuve de droits et la revue humaine sont nécessaires.")
        row = self.db.one("SELECT * FROM media WHERE id=?", (media_id,))
        if not row or row["revoked"]:
            raise DomainError("Média absent ou retiré. Un retrait ne peut pas être annulé par une simple modification.")
        self.db.execute("UPDATE media SET rights=?,evidence=?,reviewed=?,sensitive=?,caption=? WHERE id=?",
                        (rights, evidence, int(reviewed), int(sensitive), caption, media_id))
        self.db.event("rights", "Revue des droits enregistrée", f"Média #{media_id} : {rights}")

    def require_publishable(self, media_ids):
        paths = []
        for media_id in media_ids:
            row = self.db.one("SELECT * FROM media WHERE id=?", (media_id,))
            if not row or row["revoked"] or not row["reviewed"] or row["rights"] not in ALLOWED_RIGHTS or not row["evidence"].strip():
                raise DomainError(f"Le média #{media_id} n'a pas d'autorisation de diffusion validée.")
            denied = self.db.one("""SELECT p.id FROM provenance p JOIN sources s ON s.id=p.source_id
                LEFT JOIN channels c ON c.id=s.channel_id WHERE p.media_id=?
                AND (s.rights NOT IN ('own','partner','licensed') OR c.protected=1)""", (media_id,))
            if denied:
                raise DomainError(f"Les droits de la source du média #{media_id} ne sont plus valides.")
            if not Path(row["path"]).is_file():
                raise DomainError(f"Le fichier du média #{media_id} est absent.")
            paths.append(row["path"])
        return paths

    def withdraw(self, media_id, delete_file=False):
        with self.db.connect() as db:
            db.execute("UPDATE media SET revoked=1,rights='forbidden' WHERE id=?", (media_id,))
            db.execute("""UPDATE tasks SET state='cancelled',error='Autorisation de diffusion retirée',updated_at=?
                WHERE state IN ('draft','pending','scheduled') AND id IN (SELECT task_id FROM task_media WHERE media_id=?)""", (now(), media_id))
        if delete_file:
            row = self.db.one("SELECT path FROM media WHERE id=?", (media_id,))
            if row:
                path = Path(row["path"])
                if path.resolve().parent != self.directory.resolve():
                    raise DomainError("Chemin local non autorisé.")
                path.unlink(missing_ok=True)
        self.db.event("rights", "Contenu retiré", f"Média #{media_id}. Les publications distantes doivent être examinées manuellement.")

