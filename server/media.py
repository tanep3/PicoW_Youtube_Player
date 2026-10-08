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
from .library import (FPS_CHOICES, FRAME_BYTES, CROP, CONDITIONS, BusyError,
                      cache_key, source_key, video_url, interval)
from .streamer import compensate_inversion_and_bgr

class Cancelled(Exception):
    pass

class MediaJobs:
    def __init__(self, library, playback, lock, yt_dlp="yt-dlp", ffmpeg="ffmpeg", ffprobe="ffprobe"):
        self.library, self.playback, self.lock = library, playback, lock
        self.yt_dlp, self.ffmpeg, self.ffprobe = yt_dlp, ffmpeg, ffprobe
        self.job = None
        self.cancelled = threading.Event()
        self.process = None
        self.process_lock = threading.Lock()
        self.worker = None

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
                    detail = re.sub(r"https?://\S+", "[URL]", detail)
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

    def _download(self, job, start, end, duration, work):
        full = start == 0 and end == duration
        self._update(stage="download", progress=0, message="全編を取得しています" if full else "指定区間を取得しています（前後1秒の精密切出し用余白を含む）")
        # A 1-second guard means ffmpeg can trim using the source's explicit origin.
        # The requested clip is never replaced by a silently fixed duration.
        origin, covered_end = (0, duration) if full else (max(0, start-1), min(duration, end+1))
        argv = [self.yt_dlp, "--ignore-config", "--no-playlist", "--no-warnings", "--socket-timeout", "15",
                "--retries", "2", "--fragment-retries", "2", "--no-progress", "--no-part",
                "-f", "bv[height<=720]/b[height<=720]/bestvideo/best",
                "-o", str(work / "source.%(ext)s"), "--print", "after_move:filepath"]
        if not full:
            argv += ["--download-sections", f"*{origin:.3f}-{covered_end:.3f}", "--force-keyframes-at-cuts",
                     "--downloader-args", "ffmpeg_o:-threads 2"]
        argv.append(job["url"])
        self._run(argv, timeout=7200)
        files = [p for p in work.glob("source.*") if p.suffix not in (".part", ".ytdl")]
        if len(files) != 1:
            raise ValueError("取得した動画ファイルを特定できません")
        probe = self.probe(files[0])
        # Allow a source frame of rounding, never invent coverage beyond actual media.
        measured_end = min(covered_end, origin + probe["duration"])
        if measured_end + 0.1 < end:
            raise ValueError("取得区間が指定した終了時刻まで届いていません")
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
        self._update(stage="convert", message="160×80 RGB565へ変換しています", progress=0)
        temp = work / (key + ".rgb565")
        filters = CROP + f",scale=160:80:flags=bicubic,fps={fps},setpts=PTS-STARTPTS"
        argv = ["nice", "-n", "10", self.ffmpeg, "-v", "error", "-nostdin", "-threads", "2", "-filter_threads", "1",
                "-ss", f"{start-source['origin']:.3f}", "-i", str(self.library.path(source["path"])),
                "-t", f"{end-start:.3f}", "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", filters,
                "-pix_fmt", "rgb565be", "-f", "rawvideo", "pipe:1"]
        import tempfile
        with tempfile.TemporaryFile() as err, temp.open("wb") as output:
            p = self._spawn(argv, stdout=subprocess.PIPE, stderr=err)
            frames = 0
            try:
                while True:
                    self._check()
                    chunk = p.stdout.read(FRAME_BYTES)
                    if not chunk:
                        break
                    if len(chunk) != FRAME_BYTES:
                        raise ValueError("変換結果のフレーム長が不正です")
                    output.write(compensate_inversion_and_bgr(chunk))
                    frames += 1
                    if frames % fps == 0:
                        self._update(progress=min(99, round(100 * frames / (fps*(end-start)))))
                p.wait(timeout=10)
                self._check()
                if p.returncode:
                    raise ValueError("ffmpegの変換に失敗しました")
                if not frames or abs(frames/fps - (end-start)) > max(0.11, 1.1/fps):
                    raise ValueError("変換映像の長さが指定区間と一致しません")
                output.flush()
                os.fsync(output.fileno())
            finally:
                if p.poll() is None:
                    os.killpg(p.pid, signal.SIGKILL)
                    p.wait()
                p.stdout.close()
                self._finish_process(p)
        folder = self.library.video_dir(identifier) / "converted"
        folder.mkdir(exist_ok=True)
        target = folder / (key + ".rgb565")
        self._check()
        temp.replace(target)
        conversion = {"key": key, "video_id": identifier, "start": start, "end": end, "fps": fps,
                      "path": str(target.relative_to(self.library.root)), "bytes": target.stat().st_size,
                      "frames": frames, "conditions": json.dumps(CONDITIONS, sort_keys=True), "created": time.time()}
        with self.library.db() as db:
            db.execute("INSERT OR REPLACE INTO conversions VALUES(:key,:video_id,:start,:end,:fps,:path,:bytes,:frames,:conditions,:created)", conversion)
        return conversion

    def _work(self, job):
        work = self.library.root / "work" / job["id"]
        work.mkdir()
        try:
            video = self.library.video(job["video_id"])
            if not video:
                info = json.loads(self._run([self.yt_dlp, "--ignore-config", "--no-playlist", "--no-warnings",
                    "--socket-timeout", "15", "--retries", "2", "--skip-download", "--dump-single-json", job["url"]]))
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
