"""SQLite catalogue and range-aware, on-disk media cache."""
import contextlib
import hashlib
import json
import math
import re
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

FPS_CHOICES = (6, 12, 18, 24, 30)
FRAME_BYTES = 160 * 80 * 2
# Preserve the original crop when it fits; clamp only for smaller inputs.
CROP = "crop=w='min(iw,440)':h='min(ih,242)':x='(iw-ow)/2':y='max(0,min(ih-oh,(ih-220)/2))'"
CONDITIONS = {"version": 1, "width": 160, "height": 80, "crop": CROP,
              "scale": "160:80:flags=bicubic", "pixel_format": "rgb565be",
              "color_compensation": "invert-and-swap-rb", "audio": False}

class BusyError(ValueError):
    pass

def video_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("YouTube動画のURLを指定してください")
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or parts.username or parts.password or parts.port:
        raise ValueError("YouTube動画のURLを指定してください")
    host = (parts.hostname or "").lower()
    if host == "youtu.be":
        identifier = parts.path.strip("/")
    elif host in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        if parts.path == "/watch":
            identifier = parse_qs(parts.query).get("v", [""])[0]
        elif re.fullmatch(r"/(shorts|embed)/[^/]+/?", parts.path):
            identifier = parts.path.strip("/").split("/")[1]
        else:
            identifier = ""
    else:
        identifier = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", identifier):
        raise ValueError("単一のYouTube動画URLを指定してください")
    return identifier, f"https://www.youtube.com/watch?v={identifier}"

def seconds(value, default=0):
    if value is None or value == "":
        return default
    try:
        if isinstance(value, bool):
            raise ValueError()
        if isinstance(value, str) and ":" in value:
            fields = value.strip().split(":")
            if not 2 <= len(fields) <= 3 or any(not re.fullmatch(r"\d+(?:\.\d+)?", s) for s in fields):
                raise ValueError()
            nums = list(map(float, fields))
            if any(n >= 60 for n in nums[1:]):
                raise ValueError()
            result = 0.0
            for n in nums:
                result = result * 60 + n
        else:
            result = float(value)
        if not math.isfinite(result) or result < 0:
            raise ValueError()
        return round(result, 3)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("時刻は秒または HH:MM:SS で指定してください") from None

def interval(start, end, duration):
    start, end = seconds(start), seconds(end, duration)
    if not (0 <= start < end <= duration):
        raise ValueError(f"切出範囲は 0 ≤ 開始 < 終了 ≤ {duration:g}秒 にしてください")
    return start, end

def cache_key(identifier, start, end, fps):
    material = {"video_id": identifier, "start": start, "end": end, "fps": fps, **CONDITIONS}
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]

def source_key(identifier, start, end, full):
    return hashlib.sha256(json.dumps([identifier, start, end, bool(full), "source-v1"], separators=(",", ":")).encode()).hexdigest()[:24]

class Library:
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "videos").mkdir(exist_ok=True)
        (self.root / "work").mkdir(exist_ok=True)
        self.lock = threading.RLock()
        with self.db() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS videos (
                id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL,
                channel TEXT NOT NULL, uploader TEXT NOT NULL, duration REAL NOT NULL,
                thumbnail TEXT, updated REAL NOT NULL, played REAL);
              CREATE TABLE IF NOT EXISTS sources (
                key TEXT PRIMARY KEY, video_id TEXT REFERENCES videos(id) ON DELETE CASCADE,
                start REAL NOT NULL, end REAL NOT NULL, full INTEGER NOT NULL,
                path TEXT NOT NULL, bytes INTEGER NOT NULL, origin REAL NOT NULL,
                duration REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS conversions (
                key TEXT PRIMARY KEY, video_id TEXT REFERENCES videos(id) ON DELETE CASCADE,
                start REAL NOT NULL, end REAL NOT NULL, fps INTEGER NOT NULL,
                path TEXT NOT NULL, bytes INTEGER NOT NULL, frames INTEGER NOT NULL,
                conditions TEXT NOT NULL, created REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT);
            """)

    @contextlib.contextmanager
    def db(self):
        with self.lock:
            db = sqlite3.connect(self.root / "library.sqlite3")
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    def path(self, relative):
        p = (self.root / relative).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError("invalid cache path")
        return p

    def video_dir(self, identifier):
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", identifier):
            raise ValueError("invalid video id")
        p = self.root / "videos" / identifier
        p.mkdir(exist_ok=True)
        return p

    def video(self, identifier):
        with self.db() as db:
            row = db.execute("SELECT * FROM videos WHERE id=?", (identifier,)).fetchone()
            return dict(row) if row else None

    def save_video(self, identifier, url, info):
        duration = float(info.get("duration") or 0)
        if not math.isfinite(duration) or duration <= 0 or info.get("is_live"):
            raise ValueError("長さが確定した動画だけを再生できます（ライブ配信は対象外）")
        self.video_dir(identifier)
        with self.db() as db:
            db.execute("""INSERT INTO videos(id,url,title,channel,uploader,duration,updated)
              VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
              title=excluded.title,channel=excluded.channel,uploader=excluded.uploader,
              duration=excluded.duration,updated=excluded.updated""",
              (identifier, url, str(info.get("title") or f"タイトル未取得 · {identifier}")[:500],
               str(info.get("channel") or info.get("uploader") or "投稿者不明")[:300],
               str(info.get("uploader") or "")[:300], duration, time.time()))
        return self.video(identifier)

    def find_source(self, identifier, start, end):
        with self.db() as db:
            rows = db.execute("SELECT * FROM sources WHERE video_id=? AND start<=? AND end>=? ORDER BY bytes",
                              (identifier, start, end)).fetchall()
        return next((dict(r) for r in rows if self.path(r["path"]).is_file()), None)

    def conversion(self, key):
        with self.db() as db:
            row = db.execute("SELECT * FROM conversions WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        result = dict(row)
        p = self.path(result["path"])
        if not p.is_file() or p.stat().st_size != result["frames"] * FRAME_BYTES or result["frames"] <= 0:
            return None
        return result

    def preference(self, key, value=...):
        with self.db() as db:
            if value is ...:
                row = db.execute("SELECT value FROM preferences WHERE key=?", (key,)).fetchone()
                return row[0] if row else None
            db.execute("INSERT INTO preferences VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, value))

    def history(self):
        with self.db() as db:
            videos = [dict(r) for r in db.execute("SELECT * FROM videos ORDER BY COALESCE(played,updated) DESC")]
            for video in videos:
                video["sources"] = [dict(r) for r in db.execute("SELECT * FROM sources WHERE video_id=?", (video["id"],))]
                video["conversions"] = [dict(r) for r in db.execute("SELECT * FROM conversions WHERE video_id=? ORDER BY created DESC", (video["id"],))]
                video["bytes"] = sum(x["bytes"] for x in video["sources"] + video["conversions"])
                thumb = video.get("thumbnail")
                if thumb and self.path(thumb).is_file():
                    video["bytes"] += self.path(thumb).stat().st_size
                video["thumbnail_url"] = f"/thumbnail/{video['id']}" if thumb else None
                # Physical paths are not needed by the browser.
                for row in video["sources"] + video["conversions"]:
                    row.pop("path", None)
        return videos

    def usage(self):
        groups = {"source": 0, "converted": 0, "thumbnail": 0, "other": 0}
        for p in self.root.rglob("*"):
            if not p.is_file() or p.is_symlink():
                continue
            group = "converted" if p.suffix == ".rgb565" else "thumbnail" if p.name == "thumbnail.jpg" else "source" if p.parent.name == "sources" else "other"
            groups[group] += p.stat().st_size
        return {**groups, "total": sum(groups.values()), "free": shutil.disk_usage(self.root).free}

    def delete_video(self, identifier):
        # App lock must already exclude playback and jobs for this record.
        directory = self.root / "videos" / identifier
        trash = self.root / "work" / ("delete-" + uuid.uuid4().hex)
        moved = False
        try:
            with self.db() as db:
                if not db.execute("SELECT 1 FROM videos WHERE id=?", (identifier,)).fetchone():
                    raise ValueError("履歴が見つかりません")
                if directory.exists():
                    directory.rename(trash)
                    moved = True
                db.execute("DELETE FROM videos WHERE id=?", (identifier,))
        except BaseException:
            if moved:
                trash.rename(directory)
            raise
        if moved:
            shutil.rmtree(trash)
