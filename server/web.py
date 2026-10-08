"""LAN URL player: python3 -m server.web (separate from the legacy streamer)."""
import argparse
import json
import mimetypes
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .library import BusyError, FPS_CHOICES, Library
from .media import MediaJobs
from .playback import Playback

class Application:
    def __init__(self, data_dir, yt_dlp="/usr/local/bin/yt-dlp", ffmpeg="/usr/local/bin/ffmpeg", ffprobe="/usr/local/bin/ffprobe"):
        self.lock = threading.RLock()
        self.library = Library(data_dir)
        self.playback = Playback(self.library, self.lock)
        self.jobs = MediaJobs(self.library, self.playback, self.lock, yt_dlp, ffmpeg, ffprobe)
        saved = self.library.preference("current")
        if saved:
            conversion = self.library.conversion(saved)
            if conversion:
                self.playback.select(conversion)

    def state(self):
        with self.lock:
            return {"playback": self.playback.state(), "job": self.jobs.state(),
                    "history": self.library.history(), "usage": self.library.usage(),
                    "fps_choices": FPS_CHOICES, "defaults": {"fps": 6, "start": 0, "end": None}}

    def action(self, action, payload):
        with self.lock:
            if action == "prepare":
                return self.jobs.prepare(payload.get("url"), payload.get("fps", 6), payload.get("start"), payload.get("end"))
            if action == "play":
                conversion = self.library.conversion(payload.get("key"))
                if not conversion:
                    raise ValueError("完成キャッシュが見つかりません")
                video = self.library.video(conversion["video_id"])
                return self.jobs.prepare(video["url"], conversion["fps"], conversion["start"], conversion["end"])
            if action == "fps":
                current = self.playback.current
                if not current:
                    raise ValueError("再生中の動画がありません")
                return self.jobs.prepare(self.library.video(current["video_id"])["url"], payload.get("fps"), current["start"], current["end"])
            if action == "stop":
                self.playback.stop()
                return {"stopped": True}
            if action == "cancel":
                self.jobs.cancel()
                return {"cancelling": True}
            if action == "delete":
                identifier = payload.get("video_id")
                if not identifier or payload.get("confirmation") != identifier:
                    raise ValueError("削除する動画の確認が必要です")
                if self.playback.current and self.playback.current["video_id"] == identifier:
                    raise BusyError("再生を停止してから削除してください")
                if self.jobs.job and self.jobs.job["video_id"] == identifier and self.jobs.job["status"] == "working":
                    raise BusyError("処理を取り消して完了を待ってから削除してください")
                self.library.delete_video(identifier)
                return {"deleted": identifier}
            raise ValueError("不明な操作です")

    def close(self):
        self.jobs.close()
        self.playback.close()

class WebServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    def __init__(self, address, app):
        self.app = app
        super().__init__(address, Handler)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if self.path != "/api/state":
            super().log_message(fmt, *args)

    def _reply(self, status, body, content_type="application/json; charset=utf-8"):
        if content_type.startswith("application/json"):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if content_type.startswith("application/json") else "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/state":
            self._reply(200, self.server.app.state())
            return
        if path.startswith("/thumbnail/"):
            video = self.server.app.library.video(path.split("/")[-1])
            if video and video.get("thumbnail"):
                target = self.server.app.library.path(video["thumbnail"])
                if target.is_file():
                    self._reply(200, target.read_bytes(), "image/jpeg")
                    return
            self._reply(404, {"error": "画像がありません"})
            return
        names = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
        if path not in names:
            self._reply(404, {"error": "ページがありません"})
            return
        p = Path(__file__).parent / "static" / names[path]
        content_type = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        self._reply(200, p.read_bytes(), content_type + "; charset=utf-8")

    def do_POST(self):
        # No authentication keys; use only on the user's trusted LAN.
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            self._reply(403, {"error": "同じ画面から操作してください"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192 or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ValueError("JSONの操作リクエストが必要です")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("JSONオブジェクトが必要です")
            path = urlsplit(self.path).path
            if not path.startswith("/api/"):
                raise ValueError("不明な操作です")
            result = self.server.app.action(path[5:], payload)
            self._reply(200, result)
        except BusyError as exc:
            self._reply(409, {"error": str(exc)})
        except (ValueError, TypeError) as exc:
            self._reply(400, {"error": str(exc)})
        except Exception:
            self._reply(500, {"error": "操作に失敗しました。保存領域とサーバーの状態を確認してください"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="optional JSON configuration")
    known, _ = parser.parse_known_args()
    defaults = json.loads(known.config.read_text()) if known.config else {}
    allowed = {"data_dir", "web_host", "web_port", "tcp_host", "tcp_port", "yt_dlp", "ffmpeg", "ffprobe"}
    if set(defaults) - allowed:
        parser.error("unknown configuration keys")
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1]/"data")
    parser.add_argument("--web-host", default="127.0.0.1")
    parser.add_argument("--web-port", type=int, default=16152)
    parser.add_argument("--tcp-host", default="127.0.0.1")
    parser.add_argument("--tcp-port", type=int, default=16151)
    parser.add_argument("--no-tcp", action="store_true", help="Web/job testing without a Pico listener")
    parser.add_argument("--yt-dlp", default="/usr/local/bin/yt-dlp")
    parser.add_argument("--ffmpeg", default="/usr/local/bin/ffmpeg")
    parser.add_argument("--ffprobe", default="/usr/local/bin/ffprobe")
    parser.set_defaults(**defaults)
    args = parser.parse_args()
    if any(port in (8080, 16150) for port in (args.web_port, args.tcp_port)):
        parser.error("8080 / 16150 are reserved for existing production services")
    if not 1 <= args.web_port <= 65535 or not 1 <= args.tcp_port <= 65535 or args.web_port == args.tcp_port:
        parser.error("choose two distinct valid ports")
    for command in (args.yt_dlp, args.ffmpeg, args.ffprobe):
        if not shutil.which(command):
            parser.error(f"tool unavailable: {command}")
    app = Application(args.data_dir, args.yt_dlp, args.ffmpeg, args.ffprobe)
    server = None
    try:
        if not args.no_tcp:
            app.playback.start(args.tcp_host, args.tcp_port)
        server = WebServer((args.web_host, args.web_port), app)
        print(f"Web http://{args.web_host}:{args.web_port}; TCP {args.tcp_host}:{args.tcp_port}; data={app.library.root}", flush=True)
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        if server:
            server.server_close()
        app.close()

if __name__ == "__main__":
    main()
