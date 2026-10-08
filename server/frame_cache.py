"""Plain JPEG frame folders, plus legacy archive and RAW readers."""
import io
import json
import zipfile
from PIL import Image
from .streamer import WIDTH, HEIGHT, PAYLOAD_SIZE, image_rgb565

JPEG_LIMIT = 65536

def frame_name(index):
    return f"frame{index+1:08d}.jpg"

def cache_storage(item):
    conditions = item["conditions"]
    if isinstance(conditions, str):
        conditions = json.loads(conditions)
    if conditions.get("storage") in ("jpeg-directory", "jpeg-zip"):
        return conditions["storage"]
    if conditions.get("pixel_format") == "rgb565be" and not conditions.get("storage"):
        return "raw"
    raise ValueError("Unknown frame cache format")

def cache_kind(item):
    return "raw" if cache_storage(item) == "raw" else "jpeg"

def valid_cache(item, path):
    try:
        if item["frames"] <= 0:
            return False
        storage = cache_storage(item)
        if storage == "jpeg-directory":
            if not path.is_dir():
                return False
            entries = sorted(path.iterdir())
            return (len(entries) == item["frames"] and all(
                entry.name == frame_name(i) and entry.is_file() and not entry.is_symlink()
                and 4 <= entry.stat().st_size <= JPEG_LIMIT
                for i, entry in enumerate(entries)) and
                sum(entry.stat().st_size for entry in entries) == item["bytes"])
        if not path.is_file() or path.stat().st_size != item["bytes"]:
            return False
        if storage == "raw":
            return item["bytes"] == item["frames"] * PAYLOAD_SIZE
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            return (len(entries) == item["frames"] and all(
                entry.filename == frame_name(i) and entry.compress_type == zipfile.ZIP_STORED
                and 4 <= entry.file_size <= JPEG_LIMIT
                for i, entry in enumerate(entries)))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        return False

class FrameReader:
    def __init__(self, path, item):
        self.storage = cache_storage(item)
        self.kind = cache_kind(item)
        try:
            if self.storage == "jpeg-directory":
                self.source = path
            elif self.storage == "jpeg-zip":
                self.source = zipfile.ZipFile(path)
            else:
                self.source = path.open("rb")
        except zipfile.BadZipFile as exc:
            raise ValueError("JPEGキャッシュを開けません") from exc

    def read(self, index):
        if self.kind == "raw":
            self.source.seek(index * PAYLOAD_SIZE)
            payload = self.source.read(PAYLOAD_SIZE)
            if len(payload) != PAYLOAD_SIZE:
                raise ValueError("RAWキャッシュが途中で切れています")
            return payload
        try:
            if self.storage == "jpeg-directory":
                path = self.source / frame_name(index)
                if not 4 <= path.stat().st_size <= JPEG_LIMIT:
                    raise ValueError("JPEGキャッシュのフレームサイズが不正です")
                image_source = path
            else:
                image_source = io.BytesIO(self.source.read(frame_name(index)))
            with Image.open(image_source) as image:
                if image.format != "JPEG" or image.size != (WIDTH, HEIGHT):
                    raise ValueError("JPEGキャッシュのフレーム寸法が不正です")
                return image_rgb565(image, compensate_colors=True)
        except (zipfile.BadZipFile, KeyError) as exc:
            raise ValueError("JPEGキャッシュのフレームが欠損または破損しています") from exc

    def close(self):
        if self.storage != "jpeg-directory":
            self.source.close()
