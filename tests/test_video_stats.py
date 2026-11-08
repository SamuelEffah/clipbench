"""View counts for published Shorts: read from YouTube now and then, kept per video, shown on the Shorts list."""
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
from shorts import with_stats  # noqa: E402
from store import Store  # noqa: E402
from video_stats import CHANNEL_AT_KEY, FRESH_FOR, VideoStats  # noqa: E402

CLIENT = {"client_id": "cid", "client_secret": "s3cret"}
ROOT = Path(__file__).resolve().parents[1]


def reply(status, body):
    return yt.CurlResult(0, json.dumps(body) + yt.HTTP_MARK + str(status), "")


def listing(*items):
    return {"items": [{"id": i, "statistics": s} for i, s in items]}


class Recorder:
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, args, stdin=None, on_stderr=None):
        self.calls.append((args, stdin))
        return self.results.pop(0)


class ReadingStatistics(unittest.TestCase):
    def test_sign_in_asks_to_read_the_channel_as_well_as_upload(self):
        self.assertIn("youtube.readonly", yt.SCOPE)
        self.assertIn("youtube.upload", yt.SCOPE)

    def test_the_granted_scope_is_kept_with_the_tokens(self):
        run = Recorder(yt.CurlResult(0, json.dumps({"access_token": "at", "refresh_token": "rt", "expires_in": 60, "scope": yt.UPLOAD_SCOPE}), ""))
        tokens = yt.exchange_code(CLIENT, "c", "v", "http://x", run, now=0)
        self.assertEqual(tokens["scope"], yt.UPLOAD_SCOPE)
        self.assertFalse(yt.can_read(tokens))
        self.assertTrue(yt.can_read({**tokens, "scope": yt.SCOPE}))
        self.assertTrue(yt.can_analyze({**tokens, "scope": yt.SCOPE}))

    def test_counts_come_back_per_video_as_numbers(self):
        run = Recorder(reply(200, listing(("a1", {"viewCount": "1200", "likeCount": "30", "commentCount": "4"}), ("b2", {"viewCount": "7"}))))
        stats = yt.video_statistics("tok", ["a1", "b2", "gone"], run)
        self.assertEqual(stats, {"a1": {"views": 1200, "likes": 30, "comments": 4}, "b2": {"views": 7, "likes": None, "comments": None}})
        args, stdin = run.calls[0]
        self.assertIn("id=a1%2Cb2%2Cgone", stdin)
        self.assertIn("part=statistics", stdin)
        self.assertNotIn("tok", " ".join(args))

    def test_an_expired_token_asks_to_reconnect(self):
        with self.assertRaises(yt.YouTubeAuthError):
            yt.video_statistics("tok", ["a"], Recorder(reply(401, {"error": {"message": "x"}})))

    def test_a_token_without_the_read_permission_is_told_apart(self):
        body = {"error": {"code": 403, "errors": [{"reason": "insufficientPermissions"}], "message": "Insufficient Permission"}}
        with self.assertRaises(yt.YouTubeScopeError):
            yt.video_statistics("tok", ["a"], Recorder(reply(403, body)))

    def test_curl_failure_is_readable(self):
        with self.assertRaises(yt.YouTubeError) as cm:
            yt.video_statistics("tok", ["a"], Recorder(yt.CurlResult(6, "", "curl: (6) Could not resolve host")))
        self.assertIn("Could not resolve host", str(cm.exception))


class KeepingStatistics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "b.db")

    def test_only_finished_uploads_have_video_ids_to_ask_about(self):
        done = self.store.add_upload("one", "t", "private")
        self.store.finish_upload(done, "vid1")
        self.store.fail_upload(self.store.add_upload("two", "t", "private"), "no")
        again = self.store.add_upload("one", "t", "private")
        self.store.finish_upload(again, "vid2")
        self.assertEqual(self.store.uploaded_video_ids(), ["vid1", "vid2"])

    def test_counts_are_replaced_per_video_and_read_back(self):
        self.store.save_video_stats({"v1": {"views": 1, "likes": None, "comments": 0}}, at=10)
        self.store.save_video_stats({"v1": {"views": 5, "likes": 2, "comments": 0}, "v2": {"views": 9, "likes": 1, "comments": 1}}, at=20)
        counts = {vid: {k: r[k] for k in ("views", "likes", "comments", "fetched_at", "gone")} for vid, r in self.store.video_stats().items()}
        self.assertEqual(counts, {
            "v1": {"views": 5, "likes": 2, "comments": 0, "fetched_at": 20, "gone": False},
            "v2": {"views": 9, "likes": 1, "comments": 1, "fetched_at": 20, "gone": False}})


    def test_a_video_youtube_no_longer_lists_is_marked_gone_until_it_is_back(self):
        self.store.save_video_stats({"v1": {"views": 5, "likes": 1, "comments": 0}}, at=10, asked=["v1", "v2"])
        stats = self.store.video_stats()
        self.assertFalse(stats["v1"]["gone"])
        self.assertEqual({k: stats["v2"][k] for k in ("views", "likes", "comments", "fetched_at", "gone")}, {"views": 0, "likes": None, "comments": None, "fetched_at": 10, "gone": True})
        self.store.save_video_stats({"v2": {"views": 3, "likes": None, "comments": None}}, at=20, asked=["v2"])
        self.assertEqual((self.store.video_stats()["v2"]["views"], self.store.video_stats()["v2"]["gone"]), (3, False))


class PullingStatistics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = Store(root / "b.db")
        self.client = root / "client.json"
        self.client.write_text(json.dumps({"installed": CLIENT}))
        self.now = 1000.0
        self.store.set_setting(yt.TOKEN_KEY, {"access_token": "at", "refresh_token": "rt", "expires_at": 9999, "scope": f"{yt.UPLOAD_SCOPE} {yt.READ_SCOPE}"})

    def puller(self, *results):
        self.store.set_setting(CHANNEL_AT_KEY, self.now)  # the channel was listed just now; these tests are about the rest
        self.run = Recorder(*results)
        return VideoStats(self.store, self.client, run=self.run, clock=lambda: self.now)

    def upload(self, short, video_id):
        self.store.finish_upload(self.store.add_upload(short, "t", "private"), video_id)

    def test_pulls_every_published_video_in_batches_of_fifty_and_remembers_when(self):
        for i in range(60):
            self.upload("s", f"v{i}")
        puller = self.puller(reply(200, listing(*((f"v{i}", {"viewCount": str(i)}) for i in range(50)))),
                             reply(200, listing(*((f"v{i}", {"viewCount": str(i)}) for i in range(50, 60)))))
        self.assertTrue(puller.stale())
        puller.refresh()
        self.assertEqual(len(self.run.calls), 2)
        self.assertIn("id=v0%2C", self.run.calls[0][1])
        self.assertIn("id=v50%2C", self.run.calls[1][1])
        self.assertEqual(self.store.video_stats()["v59"]["views"], 59)
        self.assertFalse(puller.stale())
        self.assertEqual((puller.status()["pulled_at"], puller.status()["message"]), (1000.0, ""))

    def test_a_deleted_video_is_remembered_as_gone(self):
        self.upload("s", "kept")
        self.upload("s", "deleted")
        puller = self.puller(reply(200, listing(("kept", {"viewCount": "2"}))))
        puller.refresh()
        stats = self.store.video_stats()
        self.assertFalse(stats["kept"]["gone"])
        self.assertTrue(stats["deleted"]["gone"])

    def test_nothing_published_means_no_request_and_the_first_upload_is_looked_at_straight_away(self):
        puller = self.puller()
        puller.refresh()
        self.assertEqual(self.run.calls, [])
        self.assertTrue(puller.stale())

    def test_fresh_counts_are_not_asked_for_again_until_an_hour_passes(self):
        self.upload("s", "v1")
        puller = self.puller(reply(200, listing(("v1", {"viewCount": "1"}))), reply(200, listing(("v1", {"viewCount": "2"}))))
        self.assertTrue(puller.refresh_soon())
        puller.wait()
        self.assertFalse(puller.refresh_soon())
        self.now += FRESH_FOR + 1
        self.assertTrue(puller.refresh_soon())
        puller.wait()
        self.assertEqual(self.store.video_stats()["v1"]["views"], 2)

    def test_a_sign_in_without_read_permission_says_to_connect_again(self):
        self.upload("s", "v1")
        body = {"error": {"errors": [{"reason": "insufficientPermissions"}], "message": "Insufficient Permission"}}
        puller = self.puller(reply(403, body))
        puller.refresh()
        self.assertEqual(puller.status()["message"], "Connect YouTube again to see views")
        self.assertTrue(puller.status()["needs_reconnect"])
        self.assertIsNotNone(self.store.get_setting(yt.TOKEN_KEY), "uploads must keep working")

    def test_an_old_sign_in_is_known_to_need_reconnecting_before_any_pull(self):
        self.store.set_setting(yt.TOKEN_KEY, {"access_token": "at", "refresh_token": "rt", "expires_at": 9999})
        self.assertTrue(self.puller().status()["needs_reconnect"])

    def test_other_failures_keep_the_old_counts_and_say_why(self):
        self.upload("s", "v1")
        self.store.save_video_stats({"v1": {"views": 4, "likes": None, "comments": None}}, at=1)
        puller = self.puller(yt.CurlResult(7, "", "curl: (7) Failed to connect"))
        puller.refresh()
        self.assertIn("Failed to connect", puller.status()["message"])
        self.assertEqual(self.store.video_stats()["v1"]["views"], 4)
        self.assertTrue(puller.stale(), "a failed pull is tried again next time")

    def test_without_a_sign_in_there_is_nothing_to_do_until_one_is_made(self):
        self.store.delete_setting(yt.TOKEN_KEY)
        self.upload("s", "v1")
        puller = self.puller()
        puller.refresh()
        self.assertEqual(self.run.calls, [])
        self.assertEqual(puller.status(), {"pulled_at": None, "message": "", "needs_reconnect": False})
        self.assertTrue(puller.stale(), "connecting later must not wait an hour for the first counts")


class ShowingStatistics(unittest.TestCase):
    def test_rows_get_the_counts_of_their_uploaded_video(self):
        rows = [{"name": "a", "upload": {"state": "done", "video_id": "v1"}}, {"name": "b", "upload": {"state": "none"}}]
        out = with_stats(rows, {"v1": {"views": 3, "likes": 1, "comments": 0, "fetched_at": 5}})
        self.assertEqual(out[0]["stats"], {"views": 3, "likes": 1, "comments": 0, "fetched_at": 5})
        self.assertIsNone(out[1]["stats"])
        self.assertNotIn("stats", rows[0])

    def test_the_shorts_list_carries_counts_and_asks_for_fresh_ones(self):
        handler = object.__new__(clipper.Handler)
        handler.host_ok = lambda: True
        handler.path = "/api/shorts"
        handler.send_json = mock.Mock()
        puller, store = mock.Mock(), mock.Mock()
        store.video_stats.return_value = {"v1": {"views": 8, "likes": 0, "comments": 0, "fetched_at": 1}}
        store.list_projects.return_value = []
        rows = [{"name": "a", "upload": {"state": "done", "video_id": "v1"}}]
        with mock.patch.object(clipper, "video_stats", puller), mock.patch.object(clipper, "store", store), \
             mock.patch.object(clipper, "publisher", mock.Mock()), mock.patch.object(clipper, "list_shorts", return_value=rows):
            handler.do_GET()
        puller.refresh_soon.assert_called_once_with()
        self.assertEqual(handler.send_json.call_args.args[0][0]["stats"]["views"], 8)

    def test_the_pull_status_has_its_own_route(self):
        handler = object.__new__(clipper.Handler)
        handler.host_ok = lambda: True
        handler.path = "/api/video-stats"
        handler.send_json = mock.Mock()
        puller = mock.Mock()
        puller.status.return_value = {"pulled_at": 1, "message": "", "needs_reconnect": False}
        with mock.patch.object(clipper, "video_stats", puller):
            handler.do_GET()
        handler.send_json.assert_called_once_with({"pulled_at": 1, "message": "", "needs_reconnect": False})


@unittest.skipUnless(shutil.which("node"), "Node required")
class ShortsPage(unittest.TestCase):
    def test_cards_and_rows_show_views_and_the_count_is_short(self):
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
assert.equal(viewsText(7),'7 views');assert.equal(viewsText(1),'1 view');assert.equal(viewsText(1234),'1.2K views');assert.equal(viewsText(25400),'25K views');assert.equal(viewsText(1200000),'1.2M views');
const base={name:'here',folder:'001_here',title:'T',duration:10,size:1,rendered_at:100,has_project:false,upload:{state:'done',video_id:'v1',finished_at:200},stats:null};
const card=shortCard(base),row=dialogRow(base);
assert.match(card.innerHTML,/Uploaded as private, 10s, now/);assert.doesNotMatch(card.innerHTML,/views/);
const seen={...base,stats:{views:1234,likes:3,comments:0,fetched_at:300}};
const card2=shortCard(seen);
assert.notEqual(card2,card,'new counts repaint the card');
assert.match(card2.innerHTML,/1\.2K views, uploaded as private, 10s, now/);
assert.match(dialogRow(seen).innerHTML,/1\.2K views/);
assert.doesNotMatch(row.innerHTML,/views/);
const gone={...base,upload:{...base.upload,studio_url:'https://studio.example'},stats:{views:0,likes:null,comments:null,fetched_at:300,gone:true}};
const card3=shortCard(gone);
assert.match(card3.innerHTML,/Removed from YouTube, 10s, now/);
assert.doesNotMatch(card3.innerHTML,/views|private/);
assert.equal(card3.children[0].textContent,'Publish','a removed Short can be uploaded again');
assert.equal(card3.querySelector('.slinks').children.length,0,'no Studio link for a removed video');
assert.match(dialogRow(gone).innerHTML,/Removed from YouTube/);
assert.equal(dialogRow(gone).querySelector('.acts').children[0].textContent,'Upload');
'''
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(shutil.which("node"), "Node required")
class ShortsOfOtherProjects(unittest.TestCase):
    def test_the_list_shows_every_project_when_the_open_one_has_none(self):
        source = (ROOT / "scripts/clipper_ui/shorts.js").read_text()
        head = source.split("\nconst sizeText", 1)[0]
        script = r'''
const assert=require('node:assert/strict');
const state={project:{name:'here'}};
''' + head + r'''
const mine={name:'here'},other={name:'there'};
assert.deepEqual(shownShorts([other,mine]),[mine]);
assert.deepEqual(shownShorts([other]),[other],'with none of its own, the open project shows the others');
assert.deepEqual(shownShorts([]),[]);
assert.equal(shortsHeading([mine,other]),'1 rendered');
assert.equal(shortsHeading([other,{name:'x'}]),'2 from other projects');
assert.equal(shortsHeading([]),'');
'''
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
