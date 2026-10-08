"""One cancellable download/convert job; completion switches playback atomically."""
import json
import math
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from PIL import Image
from .library import (FPS_CHOICES, FRAME_BYTES, FIT, CONDITIONS, BusyError,
                      cache_key, source_key, video_url, interval)
from .frame_cache import frame_name, JPEG_LIMIT

class Cancelled(Exception):
    pass

class DownloadForbidden(ValueError):
    pass

class MediaJobs:
    def __init__(self, library, playback, lock, yt_dlp="yt-dlp", ffmpeg="ffmpeg", ffprobe="ffprobe", node=None):
        self.library, self.playback, self.lock = library, playback, lock
        self.yt_dlp, self.ffmpeg, self.ffprobe = yt_dlp, ffmpeg, ffprobe
        self.job = None
        self.cancelled = threading.Event()
        self.process = None
        self.process_lock = threading.Lock()
        self.worker = None
        self.node = node or shutil.which("node")
        self.https_supported = None
        self.https_signature = None

    def state(self):
        with self.lock:
            return dict(self.job) if self.job else None

    def prepare(self, url, fps=6, start=None, end=None):
        identifier, url = video_url(url)
        if isinstance(fps, bool) or fps not in FPS_CHOICES:
            raise ValueError("FPSは6 / 12 / 18 / 24 / 30から選択してください")
        # Reject malformed timestamps before starting a job; bounds need metadata.
        from .library import seconds
        seconds(start)
        seconds(end, None)
        with self.lock:
            if self.job and self.job["status"] == "working":
                raise BusyError("処理中です。取り消してから次の動画を指定してください")
            self.cancelled.clear()
            self.job = {"id": uuid.uuid4().hex, "video_id": identifier, "url": url,
                        "fps": fps, "start_input": start, "end_input": end,
                        "status": "working", "stage": "metadata", "progress": 0,
                        "message": "動画情報を確認しています", "started": time.time()}
            self.worker = threading.Thread(target=self._work, args=(dict(self.job),), daemon=True)
            self.worker.start()
            return dict(self.job)

    def _update(self, **fields):
        with self.lock:
            self.job.update(fields)

    def _check(self):
        if self.cancelled.is_set():
            raise Cancelled()

    def cancel(self):
        with self.lock:
            if not self.job or self.job["status"] != "working":
                return
            self.cancelled.set()
            self.job["message"] = "処理を取り消しています"
        with self.process_lock:
            if self.process and self.process.poll() is None:
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    def _spawn(self, argv, **kwargs):
        self._check()
        p = subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL, **kwargs)
        with self.process_lock:
            self.process = p
        if self.cancelled.is_set():
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        return p

    def _finish_process(self, p):
        with self.process_lock:
            if self.process is p:
                self.process = None

    def _run(self, argv, timeout=180):
        # Temporary files keep external-tool output bounded in process memory.
        import tempfile
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            p = self._spawn(argv, stdout=out, stderr=err)
            began = time.monotonic()
            try:
                while p.poll() is None:
                    if self.cancelled.wait(0.15) or time.monotonic()-began > timeout:
                        os.killpg(p.pid, signal.SIGKILL)
                        p.wait()
                        self._check()
                        raise ValueError("外部ツールの処理期限を超えました")
                self._check()
                if p.returncode:
                    err.seek(0)
                    detail = err.read(8000).decode(errors="replace")
                    out.seek(0)
                    detail = out.read(8000).decode(errors="replace") + "\n" + detail
                    detail = re.sub(r"https?://\S+", "[URL]", detail)
                    print(f"Media tool failed: {Path(argv[0]).name}\n{detail[-2000:].strip()}", flush=True)
                    if re.search(r"(?:HTTP (?:error )?|HTTP Error )403|403 Forbidden", detail, re.I):
                        raise DownloadForbidden("YouTubeが動画の取得URLを拒否しました（HTTP 403）。現在の再生は続きます。")
                    raise ValueError(f"{Path(argv[0]).name} の処理失敗: {detail[-700:].strip()}")
                out.seek(0)
                return out.read(8_000_000).decode(errors="replace")
            finally:
                if p.poll() is None:
                    os.killpg(p.pid, signal.SIGKILL)
                    p.wait()
                self._finish_process(p)

    def probe(self, path):
        info = json.loads(self._run([self.ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,start_time,duration:format=duration,start_time", "-of", "json", str(path)]))
        streams = info.get("streams", [])
        if not streams or not streams[0].get("width") or not streams[0].get("height"):
            raise ValueError("取得したファイルに映像がありません")
        stream, fmt = streams[0], info.get("format", {})
        duration = float(stream.get("duration") or fmt.get("duration") or 0)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("取得動画の長さを検証できません")
        return {"duration": duration, "start_time": float(stream.get("start_time") or fmt.get("start_time") or 0),
                "width": stream["width"], "height": stream["height"]}

    def _thumbnail(self, identifier, address):
        # Metadata pictures only, no user-controlled fetch endpoint.
        if not address or urlsplit(address).scheme != "https" or urlsplit(address).hostname not in ("i.ytimg.com", "img.youtube.com"):
            return
        try:
            with urlopen(Request(address, headers={"User-Agent": "PicoW-Player/1"}), timeout=10) as response:
                if urlsplit(response.url).hostname not in ("i.ytimg.com", "img.youtube.com"):
                    return
                data = response.read(1_000_001)
            if len(data) > 1_000_000:
                return
            import io
            with Image.open(io.BytesIO(data)) as image:
                image.thumbnail((480, 270))
                path = self.library.video_dir(identifier) / "thumbnail.jpg"
                temp = path.with_suffix(".tmp")
                image.convert("RGB").save(temp, "JPEG", quality=85)
                temp.replace(path)
            with self.library.db() as db:
                db.execute("UPDATE videos SET thumbnail=? WHERE id=?", (str(path.relative_to(self.library.root)), identifier))
        except (OSError, ValueError):
            pass  # A missing picture never blocks valid media.

    def _yt_base(self):
        args = [self.yt_dlp, "--ignore-config", "--no-playlist", "--no-warnings",
                "--socket-timeout", "15", "--retries", "2",
                "--ffmpeg-location", str(Path(self.ffmpeg).parent)]
        # yt-dlp enables Deno by default, so explicitly enable the installed Node.
        if self.node:
            args += ["--js-runtimes", "node:" + self.node]
        return args

    def _download(self, job, start, end, duration, work):
        full = start == 0 and end == duration
        if not full and job["url"].startswith("https:"):
            executable = Path(self.ffmpeg)
            signature = (executable.stat().st_mtime_ns, executable.stat().st_size)
            if self.https_signature != signature:
                protocols = self._run([self.ffmpeg, "-hide_banner", "-protocols"])
                self.https_supported = "https" in {line.strip() for line in protocols.splitlines()}
                self.https_signature = signature
            if not self.https_supported:
                raise ValueError("指定区間の取得に必要なffmpegのHTTPS機能がありません。更新担当による修正が必要です。全編取得は利用できます。")
        self._update(stage="download", progress=0, message="全編を取得しています" if full else "指定区間を取得しています（前後1秒の精密切出し用余白を含む）")
        # A 1-second guard means ffmpeg can trim using the source's explicit origin.
        # The requested clip is never replaced by a silently fixed duration.
        origin, covered_end = (0, duration) if full else (max(0, start-1), min(duration, end+1))
        argv = self._yt_base() + ["--check-formats", "--fragment-retries", "2", "--no-progress", "--no-part",
                "-f", "bv/b",
                "-S", "res:240,vcodec:h264",
                "-o", str(work / "source.%(ext)s")]
        if not full:
            argv += ["--download-sections", f"*{origin:.3f}-{covered_end:.3f}", "--force-keyframes-at-cuts",
                     "--downloader-args", "ffmpeg_o:-threads 2"]
        argv.append(job["url"])
        try:
            self._run(argv, timeout=7200)
        except DownloadForbidden:
            # Re-extract fresh URLs once and use the ordinary HLS alternative.
            # Preserve resolution preference, clip boundaries, and current play.
            self._update(message="取得URLが拒否されたため、低解像度HLSで1回再試行しています", retry=1)
            for path in work.glob("source.*"):
                if path.is_file():
                    path.unlink()  # Only this job's unregistered, incomplete download.
            retry_argv = list(argv)
            retry_argv[retry_argv.index("-f")+1] = "bv[protocol^=m3u8]/b[protocol^=m3u8]"
            self._run(retry_argv, timeout=7200)
        files = [p for p in work.glob("source.*") if p.suffix not in (".part", ".ytdl")]
        if len(files) != 1:
            raise ValueError("取得した動画ファイルを特定できません")
        probe = self.probe(files[0])
        # A clip ending at metadata EOF has the same whole-second rounding as a
        # full download. Keep measured partial coverage and duration for trimming.
        actual_end = origin + probe["duration"]
        measured_end = covered_end if full else min(covered_end, actual_end)
        at_metadata_end = end == duration
        tolerance = 1.0 if at_metadata_end else 0.1
        self._update(source_duration=probe["duration"], actual_source_end=actual_end,
                     requested_end=end, eof_rounding=at_metadata_end and actual_end < end)
        if actual_end + tolerance < end:
            raise ValueError(f"取得区間が終了まで届いていません（指定{end:.3f}秒、"
                             f"実測終端{actual_end:.3f}秒、不足{end-actual_end:.3f}秒）")
        key = source_key(job["video_id"], origin, covered_end, full)
        folder = self.library.video_dir(job["video_id"]) / "sources"
        folder.mkdir(exist_ok=True)
        target = folder / (key + files[0].suffix)
        self._check()
        files[0].replace(target)
        source = {"key": key, "video_id": job["video_id"], "start": origin,
                  "end": measured_end, "full": int(full), "path": str(target.relative_to(self.library.root)),
                  "bytes": target.stat().st_size, "origin": origin, "duration": probe["duration"]}
        with self.library.db() as db:
            db.execute("INSERT OR REPLACE INTO sources VALUES(:key,:video_id,:start,:end,:full,:path,:bytes,:origin,:duration)", source)
        return source

    def convert(self, source, identifier, start, end, fps, work):
        key = cache_key(identifier, start, end, fps)
        self._update(stage="convert", message="160×80 JPEGへ変換しています", progress=0)
        frames_dir = work / (key + "-frames")
        frames_dir.mkdir()
        filters = FIT + f",fps={fps},setpts=PTS-STARTPTS"
        argv = ["nice", "-n", "10", self.ffmpeg, "-v", "error", "-nostdin", "-threads", "2", "-filter_threads", "1",
                "-ss", f"{start-source['origin']:.3f}", "-i", str(self.library.path(source["path"])),
                "-t", f"{end-start:.3f}", "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", filters,
                "-c:v", "mjpeg", "-q:v", "5", "-pix_fmt", "yuvj420p", "-f", "image2",
                "-progress", "pipe:1", str(frames_dir / "frame%08d.jpg")]
        import tempfile
        with tempfile.TemporaryFile() as err:
            process = self._spawn(argv, stdout=subprocess.PIPE, stderr=err, text=True)
            try:
                for line in process.stdout:
                    self._check()
                    if line.startswith("frame="):
                        count = int(line.split("=", 1)[1])
                        self._update(progress=min(95, round(95 * count / (fps*(end-start)))))
                process.wait(timeout=10)
                self._check()
                if process.returncode:
                    err.seek(0)
                    raise ValueError("JPEG変換に失敗しました: " + err.read(1000).decode(errors="replace"))
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                process.stdout.close()
                self._finish_process(process)
        paths = sorted(frames_dir.iterdir())
        frames = len(paths)
        available = min(end-start, source.get("duration", end-source["origin"]) + source["origin"] - start)
        if not frames or abs(frames/fps - available) > max(0.11, 1.1/fps):
            raise ValueError("変換映像の長さが指定区間と一致しません")
        total_bytes = 0
        for i, path in enumerate(paths):
            self._check()
            if path.name != frame_name(i) or not 4 <= path.stat().st_size <= JPEG_LIMIT:
                raise ValueError("JPEG連番またはフレームサイズが不正です")
            with Image.open(path) as image:
                if image.format != "JPEG" or image.size != (160, 80):
                    raise ValueError("JPEGフレームの寸法が不正です")
                image.verify()
            total_bytes += path.stat().st_size
            if i % max(1, fps) == 0:
                self._update(progress=95 + round(4 * (i+1) / frames))
        folder = self.library.video_dir(identifier) / "converted"
        folder.mkdir(exist_ok=True)
        target = folder / key
        self._check()
        # Replace a previous generated folder only after the new frames pass checks.
        # Keep it until both publication and database registration succeed.
        previous = work / (key + "-previous")
        if target.exists():
            target.rename(previous)
        try:
            frames_dir.rename(target)
            conversion = {"key": key, "video_id": identifier, "start": start, "end": end, "fps": fps,
                          "path": str(target.relative_to(self.library.root)), "bytes": total_bytes,
                          "frames": frames, "conditions": json.dumps(CONDITIONS, sort_keys=True), "created": time.time()}
            with self.library.db() as db:
                db.execute("INSERT OR REPLACE INTO conversions VALUES(:key,:video_id,:start,:end,:fps,:path,:bytes,:frames,:conditions,:created)", conversion)
        except BaseException:
            if target.exists():
                shutil.rmtree(target)
            if previous.exists():
                previous.rename(target)
            raise
        if previous.exists():
            shutil.rmtree(previous)
        return conversion

    def _work(self, job):
        work = self.library.root / "work" / job["id"]
        work.mkdir()
        try:
            video = self.library.video(job["video_id"])
            if not video:
                info = json.loads(self._run(self._yt_base() + ["--skip-download", "--dump-single-json", job["url"]]))
                if info.get("id") != job["video_id"] or info.get("_type") == "playlist":
                    raise ValueError("単一動画の情報を取得できません")
                video = self.library.save_video(job["video_id"], job["url"], info)
                self._thumbnail(job["video_id"], info.get("thumbnail"))
            start, end = interval(job["start_input"], job["end_input"], video["duration"])
            self._update(start=start, end=end)
            key = cache_key(job["video_id"], start, end, job["fps"])
            conversion = self.library.conversion(key)
            reused = bool(conversion)
            if not conversion:
                source = self.library.find_source(job["video_id"], start, end)
                if not source:
                    source = self._download(job, start, end, video["duration"], work)
                conversion = self.convert(source, job["video_id"], start, end, job["fps"], work)
            self._check()
            with self.lock:
                self._check()
                self.playback.select(conversion)
                self._update(status="ready", stage="ready", progress=100, reused=reused,
                             message="キャッシュから再生しました" if reused else "変換完了・先頭から再生します", finished=time.time())
        except Cancelled:
            self._update(status="cancelled", message="取り消しました。現在の再生は継続します", finished=time.time())
        except Exception as exc:
            self._update(status="failed", message=str(exc)[:800], finished=time.time())
        finally:
            # Only this job's incomplete staging is removed. Completed caches are never auto-evicted.
            shutil.rmtree(work, ignore_errors=True)

    def close(self):
        self.cancel()
        if self.worker:
            self.worker.join(timeout=4)
