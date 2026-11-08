"""How much of each published Short people watched: read from the YouTube Analytics API once a day."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import youtube as yt  # noqa: E402
from store import Store  # noqa: E402
from video_stats import CHANNEL_AT_KEY, ANALYTICS_FRESH_FOR, RECONNECT_MESSAGE, VideoStats  # noqa: E402

CLIENT = {"client_id": "cid", "client_secret": "s3cret"}
ROOT = Path(__file__).resolve().parents[1]
DAY = 86400


def reply(status, body):
    return yt.CurlResult(0, json.dumps(body) + yt.HTTP_MARK + str(status), "")


def report(headers, rows):
    return {"columnHeaders": [{"name": h} for h in headers], "rows": rows}


def stats_listing(*items):
    return {"items": [{"id": i, "statistics": s} for i, s in items]}


class Recorder:
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, args, stdin=None, on_stderr=None):
        self.calls.append((args, stdin))
        return self.results.pop(0)


class ReadingRetention(unittest.TestCase):
    def test_sign_in_asks_for_analytics_too(self):
        self.assertIn("yt-analytics.readonly", yt.SCOPE)
        self.assertTrue(yt.can_analyze({"scope": yt.SCOPE}))
        self.assertFalse(yt.can_analyze({"scope": f"{yt.UPLOAD_SCOPE} {yt.READ_SCOPE}"}))

    def test_watch_share_and_duration_come_back_per_video(self):
        run = Recorder(reply(200, report(["video", "views", "averageViewDuration", "averageViewPercentage"], [["a1", 120, 18, 62.5], ["b2", 3, 30, 101.2]])))
        out = yt.video_retention("tok", ["a1", "b2", "gone"], run, "2020-01-01", "2026-11-07")
        self.assertEqual(out, {"a1": {"avg_duration": 18.0, "avg_percent": 62.5}, "b2": {"avg_duration": 30.0, "avg_percent": 101.2}})
        args, stdin = run.calls[0]
        self.assertIn("youtubeanalytics.googleapis.com/v2/reports", stdin)
        self.assertIn("ids=channel%3D%3DMINE", stdin)
        self.assertIn("filters=video%3D%3Da1%2Cb2%2Cgone", stdin)
        self.assertIn("startDate=2020-01-01", stdin)
        self.assertIn("endDate=2026-11-07", stdin)
        self.assertNotIn("tok", " ".join(args))

    def test_the_retention_curve_is_a_list_of_shares_watched_along_the_video(self):
        rows = [[i / 100, 1 - i / 200] for i in range(100)]
        run = Recorder(reply(200, report(["elapsedVideoTimeRatio", "audienceWatchRatio"], rows)))
        curve = yt.retention_curve("tok", "a1", run, "2020-01-01", "2026-11-07")
        self.assertEqual(len(curve), 100)
        self.assertEqual((curve[0], curve[50]), (1.0, 0.75))
        self.assertIn("filters=video%3D%3Da1", run.calls[0][1])
        self.assertIn("metrics=audienceWatchRatio", run.calls[0][1])

    def test_no_rows_means_nothing_yet(self):
        self.assertEqual(yt.video_retention("tok", ["a1"], Recorder(reply(200, {"columnHeaders": []})), "2020-01-01", "2026-11-07"), {})
        self.assertEqual(yt.retention_curve("tok", "a1", Recorder(reply(200, {"columnHeaders": []})), "2020-01-01", "2026-11-07"), [])

    def test_missing_permission_is_told_apart(self):
        body = {"error": {"code": 403, "errors": [{"reason": "forbidden"}], "message": "Forbidden"}}
        with self.assertRaises(yt.YouTubeScopeError):
            yt.video_retention("tok", ["a1"], Recorder(reply(403, body)), "2020-01-01", "2026-11-07")

    def test_api_not_enabled_says_so(self):
        body = {"error": {"code": 403, "errors": [{"reason": "accessNotConfigured"}], "message": "YouTube Analytics API has not been used"}}
        with self.assertRaises(yt.YouTubeError) as cm:
            yt.video_retention("tok", ["a1"], Recorder(reply(403, body)), "2020-01-01", "2026-11-07")
        self.assertIn("YouTube Analytics API", str(cm.exception))
        self.assertIn("Google Cloud", str(cm.exception))


class KeepingRetention(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "b.db")

    def test_retention_sits_beside_the_counts(self):
        self.store.save_video_stats({"v1": {"views": 5, "likes": 1, "comments": 0}}, at=10)
        self.store.save_video_analytics({"v1": {"avg_duration": 18.0, "avg_percent": 62.5, "retention": [1.0, 0.5]}}, at=20)
        row = self.store.video_stats()["v1"]
        self.assertEqual((row["views"], row["avg_duration"], row["avg_percent"], row["retention"], row["analytics_at"]), (5, 18.0, 62.5, [1.0, 0.5], 20))

    def test_retention_before_counts_still_keeps_a_row(self):
        self.store.save_video_analytics({"v2": {"avg_duration": 1.0, "avg_percent": 10.0, "retention": []}}, at=20)
        row = self.store.video_stats()["v2"]
        self.assertEqual((row["views"], row["avg_percent"], row["gone"]), (0, 10.0, False))

    def test_a_row_without_retention_reads_as_none(self):
        self.store.save_video_stats({"v1": {"views": 5, "likes": 1, "comments": 0}}, at=10)
        row = self.store.video_stats()["v1"]
        self.assertEqual((row["avg_duration"], row["avg_percent"], row["retention"], row["analytics_at"]), (None, None, None, None))


class PullingRetention(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = Store(root / "b.db")
        self.client = root / "client.json"
        self.client.write_text(json.dumps({"installed": CLIENT}))
        self.now = 1_700_000_000.0
        self.store.set_setting(yt.TOKEN_KEY, {"access_token": "at", "refresh_token": "rt", "expires_at": 9e9, "scope": yt.SCOPE})
        self.store.finish_upload(self.store.add_upload("s", "t", "private"), "v1")

    def puller(self, *results):
        self.store.set_setting(CHANNEL_AT_KEY, self.now)  # the channel was listed just now; these tests are about the rest
        self.run = Recorder(*results)
        return VideoStats(self.store, self.client, run=self.run, clock=lambda: self.now)

    def counts(self):
        return reply(200, stats_listing(("v1", {"viewCount": "9"})))

    def retention(self, percent=55.0):
        return reply(200, report(["video", "views", "averageViewDuration", "averageViewPercentage"], [["v1", 9, 12.0, percent]]))

    def curve(self):
        return reply(200, report(["elapsedVideoTimeRatio", "audienceWatchRatio"], [[0, 1.0], [0.5, 0.6]]))

    def days(self):
        return reply(200, report(["day", "views"], [["2026-10-03", 4]]))

    def test_counts_then_retention_then_one_curve_per_video(self):
        puller = self.puller(self.counts(), self.retention(), self.curve(), self.days())
        puller.refresh()
        self.assertEqual(len(self.run.calls), 4)
        row = self.store.video_stats()["v1"]
        self.assertEqual((row["views"], row["avg_percent"], row["retention"]), (9, 55.0, [1.0, 0.6]))
        self.assertEqual(puller.status()["message"], "")

    def test_retention_is_asked_once_a_day_while_counts_stay_hourly(self):
        puller = self.puller(self.counts(), self.retention(), self.curve(), self.days(), self.counts(), self.counts(), self.retention(80.0), self.curve(), self.days())
        puller.refresh()
        self.now += 3601
        puller.refresh()
        self.assertEqual(len(self.run.calls), 5, "an hour later only the counts are read again")
        self.now += ANALYTICS_FRESH_FOR
        self.store.set_setting(CHANNEL_AT_KEY, self.now)
        puller.refresh()
        self.assertEqual(len(self.run.calls), 9)
        self.assertEqual(self.store.video_stats()["v1"]["avg_percent"], 80.0)

    def test_a_sign_in_without_analytics_still_reads_counts_and_says_to_connect_again(self):
        self.store.set_setting(yt.TOKEN_KEY, {"access_token": "at", "refresh_token": "rt", "expires_at": 9e9, "scope": f"{yt.UPLOAD_SCOPE} {yt.READ_SCOPE}"})
        puller = self.puller(self.counts())
        self.assertTrue(puller.status()["needs_reconnect"])
        puller.refresh()
        self.assertEqual(self.store.video_stats()["v1"]["views"], 9)
        self.assertEqual(len(self.run.calls), 1)

    def test_a_removed_video_gets_no_curve_request(self):
        puller = self.puller(reply(200, stats_listing()), reply(200, {"columnHeaders": []}), self.days())
        puller.refresh()
        self.assertEqual(len(self.run.calls), 3)
        self.assertTrue(self.store.video_stats()["v1"]["gone"])

    def test_a_failed_retention_read_keeps_the_counts_and_says_why(self):
        puller = self.puller(self.counts(), yt.CurlResult(7, "", "curl: (7) Failed to connect"))
        puller.refresh()
        self.assertEqual(self.store.video_stats()["v1"]["views"], 9)
        self.assertIn("Failed to connect", puller.status()["message"])
        self.assertTrue(puller.stale(), "retention is tried again next time")


@unittest.skipUnless(shutil.which("node"), "Node required")
class ShortsPage(unittest.TestCase):
    def test_the_card_says_how_much_was_watched(self):
        source = (ROOT / "scripts/clipper_ui/shorts.js").read_text()

        def function(name):
            return "function " + name + "(" + source.split("function " + name + "(", 1)[1].split("\n}\n", 1)[0] + "\n}"
        script = r'''
const assert=require('node:assert/strict');
const element=()=>({children:[],nodes:{},style:{},attrs:{},lastChild:{nodeValue:''},setAttribute(k,v){this.attrs[k]=v;},append(...els){this.children.push(...els);},prepend(el){this.children.unshift(el);},querySelector(q){return this.nodes[q]||=(element());}});
const document={createElement(){return element();}},state={project:{name:'here'}};
const esc=String,sizeText=String,ago=()=> 'just now',agoShort=()=> 'now';
const openShort=()=>{},AUTH_PROBLEM=/auth/;
''' + function("viewsText") + function("watchedText") + function("statusOf") + function("shortCard") + function("dialogRow") + r'''
assert.equal(watchedText(62.5),'63% watched');assert.equal(watchedText(101.2),'100% watched');assert.equal(watchedText(null),'');
const base={name:'here',folder:'001_here',title:'T',duration:10,size:1,rendered_at:100,has_project:false,upload:{state:'done',video_id:'v1',finished_at:200},stats:{views:1234,likes:3,comments:0,fetched_at:300,gone:false,avg_percent:62.5,avg_duration:18}};
assert.match(shortCard(base).innerHTML,/1\.2K views, 63% watched, uploaded as private, 10s, now/);
assert.match(dialogRow(base).innerHTML,/1\.2K views, 63% watched, just now/);
const unseen={...base,stats:{...base.stats,avg_percent:null}};
assert.match(shortCard(unseen).innerHTML,/1\.2K views, uploaded as private, 10s, now/);
'''
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
