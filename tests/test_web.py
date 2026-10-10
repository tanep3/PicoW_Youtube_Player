import contextlib
import http.client
import json
import io
import os
import zipfile
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial

from server.library import (BusyError, CONDITIONS, FRAME_BYTES, cache_key, interval,
                            seconds, source_key, video_url)
from PIL import Image
from server.frame_cache import FrameReader, frame_name
from server.media import Cancelled, DownloadForbidden
from server.streamer import HEADER
from server.web import Application, WebServer

VIDEO = "abcdefghijk"
URL = "https://www.youtube.com/watch?v=" + VIDEO

class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Application(Path(self.tmp.name) / "data")
        self.app.library.save_video(VIDEO, URL, {"title": "テスト動画", "channel": "投稿者", "duration": 4})

    def tearDown(self):
        self.app.close()
        self.tmp.cleanup()

    def conversion(self, identifier=VIDEO, fps=6, value=0xffff, storage="jpeg"):
        conditions = dict(CONDITIONS)
        if storage == "raw":
            conditions = {"version":1,"width":160,"height":80,"pixel_format":"rgb565be"}
        key = cache_key(identifier, 0, 4, fps, conditions)
        p = self.app.library.video_dir(identifier) / "converted" / (key if storage=="jpeg" else key + ".rgb565")
        p.parent.mkdir(exist_ok=True)
        if storage == "jpeg":
            # Choose black/white for wire-exact JPEG protocol fixtures.
            inverted=value^0xffff
            word=((inverted&31)<<11)|(inverted&0x7e0)|(inverted>>11)
            rgb=((word>>11)*255//31,((word>>5)&63)*255//63,(word&31)*255//31)
            image=Image.new("RGB",(160,80),rgb);data=io.BytesIO();image.save(data,"JPEG",quality=95,subsampling=0)
            p.mkdir()
            for i in range(4*fps):(p/frame_name(i)).write_bytes(data.getvalue())
        else:
            payload = value.to_bytes(2, "big") * (FRAME_BYTES//2)
            p.write_bytes(payload * (4*fps))
        item = {"key": key, "video_id": identifier, "start": 0, "end": 4, "fps": fps,
                "path": str(p.relative_to(self.app.library.root)), "bytes": sum(x.stat().st_size for x in p.iterdir()) if storage=="jpeg" else p.stat().st_size,
                "frames": 4*fps, "conditions": json.dumps(conditions), "created": time.time()}
        with self.app.library.db() as db:
            db.execute("INSERT INTO conversions VALUES(:key,:video_id,:start,:end,:fps,:path,:bytes,:frames,:conditions,:created)", item)
        return item

    def wait_job(self):
        self.app.jobs.worker.join(timeout=10)
        self.assertFalse(self.app.jobs.worker.is_alive())
        return self.app.jobs.state()

class WebTests(Fixture):
    def test_url_and_ranges(self):
        self.assertEqual(video_url("https://youtu.be/abcdefghijk?t=12")[0], VIDEO)
        self.assertEqual(video_url("https://www.youtube.com/shorts/abcdefghijk")[0], VIDEO)
        for value in ("file:///tmp/a", "https://example.com/watch?v=abcdefghijk", "https://youtube.com/playlist?list=x", "https://youtube.com:8080/watch?v=abcdefghijk"):
            with self.assertRaises(ValueError): video_url(value)
        self.assertEqual(interval("", "", 3600), (0, 3600))
        self.assertEqual(interval("1:02.5", "2:00", 3600), (62.5, 120))
        for a,b in ((-1,3),(3,3),(2,5),(0,"nan"),("00:61",3)):
            with self.assertRaises(ValueError): interval(a,b,4)
        self.assertEqual(seconds("1:00:00"), 3600)

    def test_cache_identity_and_complete_validation(self):
        first = self.conversion()
        self.assertNotEqual(first["key"], cache_key(VIDEO,0,4,12))
        self.assertNotEqual(first["key"], cache_key(VIDEO,1,4,6))
        self.assertNotEqual(first["key"], cache_key(VIDEO,0,3,6))
        self.assertIsNotNone(self.app.library.conversion(first["key"]))
        (self.app.library.path(first["path"])/frame_name(0)).write_bytes(b"incomplete")
        self.assertIsNone(self.app.library.conversion(first["key"]))

    def test_jpeg_folder_missing_or_extra_frame_is_not_reused(self):
        item=self.conversion();p=self.app.library.path(item["path"])
        missing=p/frame_name(0);data=missing.read_bytes();missing.unlink()
        self.assertIsNone(self.app.library.conversion(item["key"]))
        missing.write_bytes(data)
        (p/"extra.jpg").write_bytes(data)
        self.assertIsNone(self.app.library.conversion(item["key"]))

    def test_jpeg_dimensions_checked_before_rgb565_send_and_raw_preserved(self):
        item=self.conversion();p=self.app.library.path(item["path"])
        image=Image.new("RGB",(159,80));data=io.BytesIO();image.save(data,"JPEG")
        for i in range(item["frames"]):(p/frame_name(i)).write_bytes(data.getvalue())
        reader=FrameReader(p,item)
        try:
            with self.assertRaisesRegex(ValueError,"寸法"):reader.read(0)
        finally:reader.close()
        legacy=self.conversion(storage="raw",value=0x1234)
        self.assertEqual(self.app.library.conversion(legacy["key"])["storage"],"raw")
        reader=FrameReader(self.app.library.path(legacy["path"]),legacy)
        try:self.assertEqual(reader.read(0),b"\x12\x34"*(FRAME_BYTES//2))
        finally:reader.close()

    def test_legacy_jpeg_archive_still_readable(self):
        item=self.conversion();folder=self.app.library.path(item["path"])
        p=folder.with_suffix(".frames.zip")
        with zipfile.ZipFile(p,"w",compression=zipfile.ZIP_STORED) as archive:
            for f in sorted(folder.iterdir()):archive.write(f,arcname=f.name)
        conditions=json.loads(item["conditions"]);conditions["storage"]="jpeg-zip"
        item.update(path=str(p.relative_to(self.app.library.root)),bytes=p.stat().st_size,conditions=json.dumps(conditions))
        reader=FrameReader(p,item)
        try:self.assertEqual(reader.read(0),b"\xff\xff"*(FRAME_BYTES//2))
        finally:reader.close()

    def test_jpeg_folder_usage_counts_frames_as_converted(self):
        item=self.conversion()
        self.app.library.refresh_usage()  # The fixture publishes files outside MediaJobs.
        self.assertEqual(self.app.library.usage()["converted"],item["bytes"])

    def test_hour_long_cache_state_uses_usage_snapshot(self):
        count=6*3600
        folder=self.app.library.video_dir(VIDEO)/"converted"/"hour"
        folder.mkdir(parents=True)
        seed=folder/frame_name(0)
        seed.write_bytes(b"jpeg")
        for i in range(1,count):
            os.link(seed,folder/frame_name(i))
        with self.app.library.db() as db:
            db.execute("INSERT INTO conversions VALUES(?,?,?,?,?,?,?,?,?,?)",
                       ("hour",VIDEO,0,3600,6,str(folder.relative_to(self.app.library.root)),
                        4*count,count,json.dumps(CONDITIONS),time.time()))
        self.app.library.refresh_usage()
        self.assertEqual(self.app.library.usage()["converted"],4*count)
        with patch.object(self.app.library,"_scan_usage",side_effect=AssertionError("state rescanned files")):
            for _ in range(3):
                state=self.app.state()
                self.assertEqual(state["usage"]["converted"],4*count)
                self.assertEqual(state["history"][0]["conversions"][0]["frames"],count)

    def test_partial_source_never_covers_other_interval(self):
        p = self.app.library.video_dir(VIDEO)/"source.mp4";p.write_bytes(b"source")
        with self.app.library.db() as db:
            db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?)", ("partial",VIDEO,1,3,0,str(p.relative_to(self.app.library.root)),6,1,2))
        self.assertIsNotNone(self.app.library.find_source(VIDEO,1.2,2.5))
        self.assertIsNone(self.app.library.find_source(VIDEO,0,4))
        self.assertIsNone(self.app.library.find_source(VIDEO,2,3.1))
        p.write_bytes(b"bad")
        self.assertIsNone(self.app.library.find_source(VIDEO,1.2,2.5))

    def test_403_reextracts_once_with_low_resolution_hls(self):
        self.app.jobs.job={"status":"working"}
        work=self.app.library.root/"work"/"403";work.mkdir()
        calls=[]
        def download(argv,**kwargs):
            calls.append(argv)
            if len(calls)==1:
                (work/"source.mp4").write_bytes(b"incomplete")
                raise DownloadForbidden("HTTP 403")
            self.assertFalse((work/"source.mp4").exists())
            (work/"source.mp4").write_bytes(b"video")
            return ""
        with patch.object(self.app.jobs,"_run",side_effect=download), patch.object(self.app.jobs,"probe",return_value={"duration":3}):
            source=self.app.jobs._download({"video_id":VIDEO,"url":"http://fixture/video"},1,2,4,work)
        self.assertEqual(len(calls),2)
        self.assertIn("res:240,vcodec:h264",calls[1])
        self.assertIn("bv[protocol^=m3u8]/b[protocol^=m3u8]",calls[1])
        self.assertEqual(source["bytes"],5)

    def test_403_retry_is_bounded_and_never_registers_incomplete_source(self):
        self.app.jobs.job={"status":"working"}
        work=self.app.library.root/"work"/"403-fail";work.mkdir()
        with patch.object(self.app.jobs,"_run",side_effect=DownloadForbidden("HTTP 403")) as run:
            with self.assertRaises(DownloadForbidden):
                self.app.jobs._download({"video_id":VIDEO,"url":"http://fixture/video"},1,2,4,work)
        self.assertEqual(run.call_count,2)
        self.assertIsNone(self.app.library.find_source(VIDEO,1,2))

    def test_partial_download_to_eof_accepts_metadata_rounding_and_reuses(self):
        self.app.jobs.job={"status":"working"}
        work=self.app.library.root/"work"/"eof";work.mkdir()
        def download(*args, **kwargs):
            (work/"source.mp4").write_bytes(b"video")
            return ""
        # Metadata says 4s; a clip starting at 2s has guard origin 1s and
        # measured EOF 3.65s. This is a partial source, not a whole download.
        with patch.object(self.app.jobs,"_run",side_effect=download), patch.object(self.app.jobs,"probe",return_value={"duration":2.65}):
            source=self.app.jobs._download({"video_id":VIDEO,"url":"http://fixture/video"},2,4,4,work)
        self.assertFalse(source["full"])
        self.assertAlmostEqual(source["end"],3.65)
        self.assertEqual(self.app.library.find_source(VIDEO,2,4)["key"],source["key"])
        self.assertIsNone(self.app.library.find_source(VIDEO,0,4))
        self.assertIsNone(self.app.library.find_source(VIDEO,2,3.8))

    def test_download_rejects_large_eof_shortfall_and_precise_interior_shortfall(self):
        self.app.jobs.job={"status":"working"}
        for name,end,actual_duration in (("eof-short",4,1.6),("interior-short",3,1.8)):
            with self.subTest(name=name):
                work=self.app.library.root/"work"/name;work.mkdir()
                def download(*args,**kwargs):
                    (work/"source.mp4").write_bytes(b"video")
                    return ""
                with patch.object(self.app.jobs,"_run",side_effect=download), patch.object(self.app.jobs,"probe",return_value={"duration":actual_duration}):
                    with self.assertRaisesRegex(ValueError,"実測終端"):
                        self.app.jobs._download({"video_id":VIDEO,"url":"http://fixture/video"},2,end,4,work)
                self.assertIsNone(self.app.library.find_source(VIDEO,2,end))

    def test_near_eof_interior_cache_never_claims_tail(self):
        p=self.app.library.video_dir(VIDEO)/"interior.mp4";p.write_bytes(b"source")
        key=source_key(VIDEO,1,3.5,False)
        with self.app.library.db() as db:
            db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?)", (key,VIDEO,1,3.5,0,str(p.relative_to(self.app.library.root)),6,1,2.5))
        self.assertIsNotNone(self.app.library.find_source(VIDEO,2,3.5))
        self.assertIsNone(self.app.library.find_source(VIDEO,2,4))

    def test_cached_replay_fps_and_restore(self):
        first, second = self.conversion(), self.conversion(fps=12,value=0x5678)
        self.app.action("prepare", {"url":URL,"fps":6})
        self.assertEqual(self.wait_job()["status"], "ready")
        self.assertTrue(self.app.jobs.state()["reused"])
        self.assertEqual(self.app.playback.current["key"], first["key"])
        self.app.action("fps", {"fps":12})
        self.assertEqual(self.wait_job()["status"], "ready")
        self.assertEqual(self.app.playback.current["key"], second["key"])
        restored = Application(self.app.library.root)
        try: self.assertEqual(restored.playback.current["key"], second["key"])
        finally: restored.close()

    def test_failed_bounds_keep_current_movie(self):
        first = self.conversion();self.app.playback.select(first)
        self.app.action("prepare", {"url":URL,"fps":12,"end":5})
        self.assertEqual(self.wait_job()["status"], "failed")
        self.assertEqual(self.app.playback.current["key"],first["key"])

    def test_cancel_busy_delete_and_resume(self):
        first = self.conversion();self.app.playback.select(first)
        entered = threading.Event()
        def slow(*args):
            entered.set()
            while not self.app.jobs.cancelled.wait(.01): pass
            raise Cancelled()
        with patch.object(self.app.jobs,"_download",side_effect=slow):
            self.app.action("prepare", {"url":URL,"fps":12})
            self.assertTrue(entered.wait(2))
            with self.assertRaises(BusyError): self.app.action("prepare", {"url":URL})
            self.app.action("stop",{})
            with self.assertRaises(BusyError): self.app.action("delete", {"video_id":VIDEO,"confirmation":VIDEO})
            self.app.action("cancel",{})
            self.assertEqual(self.wait_job()["status"], "cancelled")
        self.app.action("play", {"key":first["key"]})
        self.assertEqual(self.wait_job()["status"],"ready")

    def test_delete_requires_stop_and_confirmation_and_one_record_only(self):
        first=self.conversion();self.app.playback.select(first)
        other="lmnopqrstuv";self.app.library.save_video(other,"https://youtu.be/"+other,{"duration":4})
        self.conversion(other)
        with self.assertRaises(ValueError):self.app.action("delete",{"video_id":VIDEO})
        with self.assertRaises(BusyError):self.app.action("delete",{"video_id":VIDEO,"confirmation":VIDEO})
        self.app.action("stop",{})
        self.app.action("delete",{"video_id":VIDEO,"confirmation":VIDEO})
        self.assertIsNone(self.app.library.video(VIDEO))
        self.assertFalse((self.app.library.root/"videos"/VIDEO).exists())
        self.assertIsNotNone(self.app.library.video(other))
        self.assertEqual(len(self.app.library.history()),1)

    def test_delete_does_not_hold_state_lock_and_blocks_same_video_prepare(self):
        entered,release=threading.Event(),threading.Event()
        def slow_delete(identifier):
            entered.set()
            self.assertTrue(release.wait(2))
        with patch.object(self.app.library,"delete_video",side_effect=slow_delete):
            deleter=threading.Thread(target=lambda:self.app.action("delete",{"video_id":VIDEO,"confirmation":VIDEO}))
            deleter.start()
            try:
                self.assertTrue(entered.wait(2))
                result=[]
                reader=threading.Thread(target=lambda:result.append(self.app.state()))
                reader.start();reader.join(.5)
                self.assertFalse(reader.is_alive(),"state waited for deletion")
                self.assertEqual(len(result[0]["history"]),1)
                with self.assertRaises(BusyError):
                    self.app.action("prepare",{"url":URL})
            finally:
                release.set();deleter.join(2)
            self.assertFalse(deleter.is_alive())

    def test_tcp_switch_frame_zero_pacing_stop_and_reconnect(self):
        a=self.conversion();other="lmnopqrstuv"
        self.app.library.save_video(other,"https://youtu.be/"+other,{"duration":4})
        b=self.conversion(other,value=0x0000)
        port=self.app.playback.start("127.0.0.1",0)
        self.app.playback.select(a)
        def read(client):
            def exact(n):
                data=b""
                while len(data)<n:
                    chunk=client.recv(n-len(data))
                    if not chunk:raise EOFError()
                    data+=chunk
                return data
            header=HEADER.unpack(exact(HEADER.size));return header,exact(header[4])
        with socket.create_connection(("127.0.0.1",port),timeout=3) as client:
            h,p=read(client);self.assertEqual(h,(b"PWF2",0,160,80,25600,1));self.assertEqual(p[:2],b"\xff\xff")
            t=time.monotonic();h,p=read(client);self.assertGreaterEqual(time.monotonic()-t,.12)
            self.app.playback.select(b)
            for _ in range(3):
                h,p=read(client)
                if p[:2]==b"\x00\x00":break
            self.assertEqual(h[1],0)
            self.assertEqual(p[:2],b"\x00\x00")
        # The status reader observes EOF and frees the single connection listener.
        time.sleep(.1)
        with socket.create_connection(("127.0.0.1",port),timeout=3) as client:
            h,p=read(client);self.assertEqual(p[:2],b"\x00\x00")
            self.app.action("stop",{})
            while True:
                try:
                    if not client.recv(30000):break
                except ConnectionResetError:break
        self.assertGreaterEqual(self.app.playback.connections,2)

    def test_state_does_not_wait_for_blocked_send_and_stop_orders_after_it(self):
        item=self.conversion(storage="raw")
        self.app.playback.select(item)
        entered,release=threading.Event(),threading.Event()
        class SlowConnection:
            def sendall(self, data):
                entered.set()
                if not release.wait(2):raise TimeoutError()
        stream=threading.Thread(target=self.app.playback._stream,args=(SlowConnection(),))
        stream.start()
        try:
            self.assertTrue(entered.wait(2))
            result=[]
            reader=threading.Thread(target=lambda:result.append(self.app.state()))
            reader.start();reader.join(.5)
            self.assertFalse(reader.is_alive(),"state waited for socket send")
            self.assertTrue(result[0]["playback"]["current"])
            stopped=threading.Event()
            stopper=threading.Thread(target=lambda:(self.app.playback.stop(),stopped.set()))
            stopper.start()
            self.assertFalse(stopped.wait(.05),"stop overtook an in-flight frame")
            release.set();stopper.join(2);stream.join(2)
            self.assertTrue(stopped.is_set())
            self.assertFalse(stream.is_alive())
            self.assertIsNone(self.app.playback.current)
        finally:
            release.set()

    def test_https_missing_is_clear_and_never_falls_back_to_whole(self):
        self.app.jobs.job={"status":"working"}
        work=self.app.library.root/"work"/"https";work.mkdir()
        with patch.object(self.app.jobs,"_run",return_value="Input:\n  http\nOutput:\n  http\n") as run:
            with self.assertRaisesRegex(ValueError,"HTTPS"):
                self.app.jobs._download({"video_id":VIDEO,"url":URL},1,2,4,work)
        self.assertEqual(run.call_count,1)
        self.assertFalse(list(work.iterdir()))

    def test_loop_uses_fixed_cache_without_loading_movie(self):
        first=self.conversion(storage="raw")
        p=self.app.library.path(first["path"])
        a=b"\xff\xff"*(FRAME_BYTES//2);b=b"\x00\x00"*(FRAME_BYTES//2)
        p.write_bytes(a+b)
        first.update(frames=2,bytes=2*FRAME_BYTES)
        self.app.playback.select(first)
        left,right=socket.socketpair()
        done=threading.Event()
        worker=threading.Thread(target=self.app.playback._stream,args=(left,done));worker.start()
        try:
            packets=[]
            for n in range(3):
                data=b""
                while len(data)<HEADER.size+FRAME_BYTES:data+=right.recv(HEADER.size+FRAME_BYTES-len(data))
                packets.append(data)
            self.assertEqual([HEADER.unpack_from(x)[1] for x in packets],[0,1,2])
            self.assertEqual([x[HEADER.size:HEADER.size+2] for x in packets],[b"\xff\xff",b"\x00\x00",b"\xff\xff"])
        finally:
            done.set();worker.join(2);left.close();right.close()
        self.assertFalse(worker.is_alive())

    def test_http_validation_history_and_csrf(self):
        web=WebServer(("127.0.0.1",0),self.app)
        thread=threading.Thread(target=web.serve_forever,daemon=True);thread.start()
        try:
            client=http.client.HTTPConnection("127.0.0.1",web.server_port,timeout=3)
            client.request("GET","/api/state");r=client.getresponse();state=json.loads(r.read())
            self.assertEqual(state["defaults"]["fps"],6)
            self.assertEqual(state["fps_choices"],[6,12,18,24,30])
            client.request("POST","/api/prepare",json.dumps({"url":"https://example.com/x"}),{"Content-Type":"application/json"});r=client.getresponse();self.assertEqual(r.status,400);r.read()
            client.request("POST","/api/stop","{}",{"Content-Type":"application/json","Origin":"https://foreign.example"});r=client.getresponse();self.assertEqual(r.status,403);r.read()
            client.request("GET","/../config.h");r=client.getresponse();self.assertEqual(r.status,404);r.read()
            client.close()
        finally:web.shutdown();web.server_close();thread.join(3)

class TrimTests(Fixture):
    @classmethod
    def setUpClass(cls):
        cls.media_tmp=tempfile.TemporaryDirectory()
        cls.full=Path(cls.media_tmp.name)/"clock.mp4"
        p=subprocess.Popen(["/usr/local/bin/ffmpeg","-v","error","-threads","2","-f","rawvideo","-pix_fmt","rgb24","-video_size","480x270","-framerate","20","-i","pipe:0","-an","-c:v","libx264","-threads","2","-preset","ultrafast","-crf","0","-g","80","-pix_fmt","yuv444p","-y",str(cls.full)],stdin=subprocess.PIPE)
        for i in range(80):p.stdin.write(bytes((i*3,i*2,20))*(480*270))
        p.stdin.close()
        if p.wait()!=0:raise RuntimeError("synthetic source failed")

    @classmethod
    def tearDownClass(cls):cls.media_tmp.cleanup()

    def install_source(self,path,origin=0,start=0,end=4):
        target=self.app.library.video_dir(VIDEO)/path.name
        target.write_bytes(path.read_bytes())
        return {"path":str(target.relative_to(self.app.library.root)),"origin":origin,"start":start,"end":end}

    def convert_range(self,source,start,end,fps=6):
        self.app.jobs.job={"status":"working"}
        work=self.app.library.root/"work"/"test";work.mkdir(exist_ok=True)
        result=self.app.jobs.convert(source,VIDEO,start,end,fps,work)
        reader=FrameReader(self.app.library.path(result["path"]),result)
        try:data=b"".join(reader.read(i) for i in range(result["frames"]))
        finally:reader.close()
        self.assertTrue(self.app.library.path(result["path"]).is_dir())
        self.assertEqual(len(list(self.app.library.path(result["path"]).glob("*.jpg"))),result["frames"])
        self.assertLess(result["bytes"],result["frames"]*FRAME_BYTES)
        return data,result

    def test_exact_cut_full_source_and_all_fps(self):
        source=self.install_source(self.full)
        cropped,item=self.convert_range(source,1.35,2.35)
        self.assertEqual(item["frames"],6);self.assertEqual(len(cropped),6*25600)
        for fps in (12,18,24,30):
            data,item=self.convert_range(source,1,2,fps)
            self.assertEqual(item["frames"],fps)
            self.assertEqual(len(data),fps*25600)
        # Contrast inaccurate stream copy with accurate transcode: copy starts at earlier keyframe.
        copied=Path(self.media_tmp.name)/"copy.mp4"
        subprocess.run(["/usr/local/bin/ffmpeg","-v","error","-ss","1.35","-i",str(self.full),"-t","1","-c","copy","-avoid_negative_ts","make_zero","-y",str(copied)],check=True)
        a=self.app.jobs.probe(copied);self.assertGreater(a["duration"],1.5)

    def test_video_edges_preserved_and_unused_area_black(self):
        from PIL import ImageDraw
        for width,height,left,right in ((480,240,0,159),(240,480,60,99)):
            with self.subTest(size=(width,height)):
                png=Path(self.tmp.name)/f"edges-{width}.png"
                movie=Path(self.tmp.name)/f"edges-{width}.mp4"
                image=Image.new("RGB",(width,height),(70,70,70));draw=ImageDraw.Draw(image)
                draw.rectangle((0,0,23,height-1),fill=(255,0,0))
                draw.rectangle((width-24,0,width-1,height-1),fill=(0,0,255))
                draw.rectangle((0,0,width-1,23),fill=(0,255,0))
                draw.rectangle((0,height-24,width-1,height-1),fill=(255,255,0))
                image.save(png)
                subprocess.run(["/usr/local/bin/ffmpeg","-v","error","-threads","2","-loop","1","-i",str(png),"-t","1","-r","6","-an","-c:v","libx264","-threads","2","-pix_fmt","yuv420p","-y",str(movie)],check=True)
                _,item=self.convert_range(self.install_source(movie),0,1)
                with Image.open(self.app.library.path(item["path"])/frame_name(0)) as output:
                    rgb=output.convert("RGB")
                    red=rgb.getpixel((left+1,40));blue=rgb.getpixel((right-1,40))
                    green=rgb.getpixel((80,1));yellow=rgb.getpixel((80,78))
                    self.assertGreater(red[0],180);self.assertLess(max(red[1:]),50)
                    self.assertGreater(blue[2],180);self.assertLess(max(blue[:2]),50)
                    self.assertGreater(green[1],180);self.assertLess(max(green[0],green[2]),50)
                    self.assertGreater(min(yellow[:2]),180);self.assertLess(yellow[2],50)
                    if left:
                        self.assertLess(max(rgb.getpixel((5,40))),12)
                        self.assertLess(max(rgb.getpixel((155,40))),12)

    def test_real_ytdlp_section_clock_and_partial_trim(self):
        # Actual installed yt-dlp + ffmpeg against a local public HTTP fixture.
        content = self.full.read_bytes()
        class Quiet(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                import re
                match = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
                begin, finish = (int(match[1]), int(match[2]) if match[2] else len(content)-1) if match else (0, len(content)-1)
                self.send_response(206 if match else 200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(finish-begin+1))
                if match:self.send_header("Content-Range", f"bytes {begin}-{finish}/{len(content)}")
                self.end_headers()
                self.wfile.write(content[begin:finish+1])
        http=ThreadingHTTPServer(("127.0.0.1",0),Quiet)
        t=threading.Thread(target=http.serve_forever,daemon=True);t.start()
        work=self.app.library.root/"work"/"section";work.mkdir()
        self.app.jobs.job={"status":"working"}
        try:
            source=self.app.jobs._download({"video_id":VIDEO,"url":f"http://127.0.0.1:{http.server_port}/clock.mp4"},1.35,2.35,4,work)
        finally:http.shutdown();http.server_close();t.join(3)
        self.assertFalse(source["full"])
        self.assertAlmostEqual(source["origin"],.35)
        self.assertLess(abs(self.app.jobs.probe(self.app.library.path(source["path"]))["start_time"]),.1)
        self.assertIsNone(self.app.library.find_source(VIDEO,0,4))
        partial_bytes,part=self.convert_range(source,1.35,2.35)
        full_bytes,full=self.convert_range(self.install_source(self.full),1.35,2.35)
        self.assertEqual(part["frames"],full["frames"])
        # The section is re-encoded: compare the time-varying colour within quantisation tolerance.
        def rgb(word):
            word=((word&31)<<11)|(word&0x7e0)|(word>>11)
            word^=0xffff
            return ((word>>11)*8,((word>>5)&63)*4,(word&31)*8)
        for n in range(part["frames"]):
            a=rgb(int.from_bytes(partial_bytes[n*25600:n*25600+2],"big"))
            b=rgb(int.from_bytes(full_bytes[n*25600:n*25600+2],"big"))
            self.assertLessEqual(max(abs(x-y) for x,y in zip(a,b)),8,(n,a,b))
