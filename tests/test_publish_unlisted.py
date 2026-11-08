"""Uploads go up unlisted with every field filled, and the app says when to make them public."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import clipper  # noqa: E402
import youtube as yt  # noqa: E402
from publisher import Publisher  # noqa: E402
from store import Store  # noqa: E402
from video_stats import BEST_DAY_KEY, CHANNEL_AT_KEY, VideoStats, best_weekday, best_time_text  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CLIENT = {"client_id": "cid", "client_secret": "s3cret"}


class Recorder:
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, args, stdin=None, on_stderr=None):
        self.calls.append((args, stdin))
        return self.results.pop(0)


def reply(status, body):
    return yt.CurlResult(0, json.dumps(body) + yt.HTTP_MARK + str(status), "")


class FillingTheFields(unittest.TestCase):
    def test_hashtags_in_the_description_become_tags(self):
        self.assertEqual(yt.hashtags("Funny bit #shorts #Streamer clips #shorts\n#anime_moment #2024"), ["shorts", "Streamer", "anime_moment", "2024"])
        self.assertEqual(yt.hashtags("no tags here"), [])

    def test_tags_stay_within_youtubes_room(self):
        many = " ".join(f"#tag{i:03d}" for i in range(200))
        tags = yt.hashtags(many)
        self.assertLessEqual(len(tags), yt.MAX_TAGS)
        self.assertLessEqual(sum(len(t) + 2 for t in tags), yt.TAGS_CHARS)

    def test_upload_goes_unlisted_with_kids_and_ai_answered_and_tags(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        video = Path(tmp.name) / "video.mp4"
        video.write_bytes(b"x" * 10)
        run = Recorder(yt.CurlResult(0, "HTTP/2 200\r\nlocation: https://up/1\r\n\r\n", ""),
                       yt.CurlResult(0, json.dumps({"id": "vid1", "status": {"privacyStatus": "unlisted"}}) + "\n__HTTP__200", ""))
        uploaded = yt.upload_video("tok", video, "Title", "Desc #shorts #clips", run, lambda p: None)
        self.assertEqual((uploaded.video_id, uploaded.privacy), ("vid1", "unlisted"))
        meta = json.loads(run.calls[0][1].split("data = ", 1)[1].strip().strip('"').encode().decode("unicode_escape"))
        self.assertEqual(meta["status"], {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": False})
        self.assertEqual(meta["snippet"]["tags"], ["shorts", "clips"])

    def test_the_privacy_youtube_kept_is_what_is_reported(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        video = Path(tmp.name) / "video.mp4"
        video.write_bytes(b"x" * 10)
        run = Recorder(yt.CurlResult(0, "HTTP/2 200\r\nlocation: https://up/1\r\n\r\n", ""),
                       yt.CurlResult(0, json.dumps({"id": "vid1", "status": {"privacyStatus": "private"}}) + "\n__HTTP__200", ""))
        self.assertEqual(yt.upload_video("tok", video, "T", "D", run, lambda p: None).privacy, "private")


class RememberingThePrivacy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = Store(root / "b.db")
        self.client = root / "client.json"
        self.client.write_text(json.dumps({"installed": CLIENT}))
        self.video = root / "video.mp4"
        self.video.write_bytes(b"v" * 10)
        self.store.set_setting(yt.TOKEN_KEY, {"access_token": "at", "refresh_token": "rt", "expires_at": 9e9, "scope": yt.SCOPE})

    def test_the_upload_record_keeps_what_youtube_made_it(self):
        uid = self.store.add_upload("s", "T", "unlisted")
        self.store.finish_upload(uid, "vid1", "private")
        self.assertEqual(self.store.latest_upload("s")["privacy"], "private")

    def test_state_says_the_privacy(self):
        run = Recorder(yt.CurlResult(0, "HTTP/2 200\r\nlocation: https://up/1\r\n\r\n", ""),
                       yt.CurlResult(0, json.dumps({"id": "vid1", "status": {"privacyStatus": "unlisted"}}) + "\n__HTTP__200", ""))
        pub = Publisher(self.store, self.client, run=run, clock=lambda: 1000.0)
        pub.start_upload("s", self.video, "T", "D")
        pub.wait("s")
        self.assertEqual((pub.state("s")["state"], pub.state("s")["privacy"]), ("done", "unlisted"))


class BestTime(unittest.TestCase):
    def test_the_busiest_weekday_over_the_last_weeks_wins(self):
        rows = [{"day": "2026-10-03", "views": 50}, {"day": "2026-10-04", "views": 10}, {"day": "2026-10-10", "views": 40}, {"day": "2026-10-05", "views": 60}]
        self.assertEqual(best_weekday(rows), "Saturday")

    def test_no_views_means_no_best_day(self):
        self.assertIsNone(best_weekday([]))
        self.assertIsNone(best_weekday([{"day": "bad", "views": 3}]))

    def test_the_suggestion_reads_as_a_day_and_an_hour(self):
        self.assertEqual(best_time_text("Saturday"), "Saturday around 5 pm")
        self.assertEqual(best_time_text(None), "")

    def test_the_daily_pull_keeps_the_best_day(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        store = Store(root / "b.db")
        client = root / "client.json"
        client.write_text(json.dumps({"installed": CLIENT}))
        store.set_setting(yt.TOKEN_KEY, {"access_token": "at", "refresh_token": "rt", "expires_at": 9e9, "scope": yt.SCOPE})
        store.set_setting(CHANNEL_AT_KEY, 1_700_000_000.0)
        store.finish_upload(store.add_upload("s", "t", "unlisted"), "v1")
        report = lambda headers, rows: reply(200, {"columnHeaders": [{"name": h} for h in headers], "rows": rows})
        run = Recorder(reply(200, {"items": [{"id": "v1", "statistics": {"viewCount": "1"}}]}),
                       report(["video", "views", "averageViewDuration", "averageViewPercentage"], []),
                       report(["day", "views"], [["2026-10-03", 9], ["2026-10-04", 2]]))
        puller = VideoStats(store, client, run=run, clock=lambda: 1_700_000_000.0)
        puller.refresh()
        self.assertEqual(store.get_setting(BEST_DAY_KEY), "Saturday")
        self.assertEqual(puller.best_day(), "Saturday")
        self.assertIn("dimensions=day", run.calls[2][1])

    def test_the_youtube_status_carries_the_best_time(self):
        handler = object.__new__(clipper.Handler)
        handler.host_ok = lambda: True
        handler.path = "/api/youtube"
        handler.send_json = mock.Mock()
        publisher, puller = mock.Mock(), mock.Mock()
        publisher.status.return_value = {"configured": True, "connected": True, "message": ""}
        puller.best_day.return_value = "Saturday"
        with mock.patch.object(clipper, "publisher", publisher), mock.patch.object(clipper, "video_stats", puller):
            handler.do_GET()
        handler.send_json.assert_called_once_with({"configured": True, "connected": True, "message": "", "best_time": "Saturday around 5 pm"})


@unittest.skipUnless(shutil.which("node"), "Node required")
class PublishPage(unittest.TestCase):
    def test_done_state_names_the_privacy_and_the_best_time(self):
        source = (ROOT / "scripts/clipper_ui/youtube.js").read_text()
        code = source.split("\nasync function ytRefresh(", 1)[0]
        script = r'''
const assert=require('node:assert/strict');
const nodes={},$=id=>nodes[id]||(nodes[id]={hidden:false,style:{},classList:{toggle(){}},textContent:''});
const setStage=()=>{},ago=()=> '2 hours ago';
''' + code + r'''
yt.status={configured:true,connected:true,best_time:'Saturday around 5 pm'};
yt.upload={state:'done',privacy:'unlisted',finished_at:1,studio_url:'s',watch_url:'w',title:'T'};
ytPaint();
assert.equal($('ytWhen').textContent,'Uploaded as unlisted, 2 hours ago. Best time to make it public: Saturday around 5 pm');
yt.upload={...yt.upload,privacy:'private'};yt.status={...yt.status,best_time:''};
ytPaint();
assert.equal($('ytWhen').textContent,'Uploaded as private, 2 hours ago');
yt.upload={state:'none'};
ytPaint();
assert.match($('ytStatus').textContent,/unlisted/);
'''
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_shorts_card_names_the_privacy(self):
        source = (ROOT / "scripts/clipper_ui/shorts.js").read_text()

        def function(name):
            return "function " + name + "(" + source.split("function " + name + "(", 1)[1].split("\n}\n", 1)[0] + "\n}"
        script = function("statusOf") + r'''
const assert=require('node:assert/strict');
assert.equal(statusOf({state:'done',privacy:'unlisted'},null).text,'Uploaded as unlisted');
assert.equal(statusOf({state:'done'},null).text,'Uploaded as private');
'''
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
