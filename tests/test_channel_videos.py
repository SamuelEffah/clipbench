"""Every video on the channel, not only the ones the app uploaded, gets its counts and watch figures pulled."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import youtube as yt  # noqa: E402
from store import Store  # noqa: E402
from video_stats import CHANNEL_FRESH_FOR, VideoStats  # noqa: E402

CLIENT = {"client_id": "cid", "client_secret": "s3cret"}


def reply(status, body):
    return yt.CurlResult(0, json.dumps(body) + yt.HTTP_MARK + str(status), "")


def channel(uploads="UUabc"):
    return reply(200, {"items": [{"id": "UCabc", "contentDetails": {"relatedPlaylists": {"uploads": uploads}}}]})


def page(*videos, next_token=None):
    body = {"items": [{"snippet": {"title": t, "publishedAt": at, "resourceId": {"kind": "youtube#video", "videoId": vid}}} for vid, t, at in videos]}
    if next_token:
        body["nextPageToken"] = next_token
    return reply(200, body)


class Recorder:
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, args, stdin=None, on_stderr=None):
        self.calls.append((args, stdin))
        return self.results.pop(0)


class ListingTheChannel(unittest.TestCase):
    def test_every_upload_comes_back_across_pages(self):
        run = Recorder(channel(), page(("a", "First", "2026-01-01T00:00:00Z"), next_token="p2"), page(("b", "Second", "2026-02-01T00:00:00Z")))
        videos = yt.channel_videos("tok", run)
        self.assertEqual(videos, [{"video_id": "a", "title": "First", "published_at": "2026-01-01T00:00:00Z"},
                                  {"video_id": "b", "title": "Second", "published_at": "2026-02-01T00:00:00Z"}])
        self.assertIn("mine=true", run.calls[0][1])
        self.assertIn("playlistId=UUabc", run.calls[1][1])
        self.assertIn("pageToken=p2", run.calls[2][1])
        self.assertNotIn("pageToken", run.calls[1][1])

    def test_no_channel_means_no_videos(self):
        self.assertEqual(yt.channel_videos("tok", Recorder(reply(200, {"items": []}))), [])

    def test_a_refused_read_asks_to_connect_again(self):
        body = {"error": {"errors": [{"reason": "insufficientPermissions"}], "message": "x"}}
        with self.assertRaises(yt.YouTubeScopeError):
            yt.channel_videos("tok", Recorder(reply(403, body)))


class KeepingChannelVideos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "b.db")

    def test_channel_videos_are_tracked_beside_the_app_uploads_without_doubles(self):
        self.store.finish_upload(self.store.add_upload("s", "t", "private"), "mine")
        self.store.save_channel_videos([{"video_id": "old", "title": "Old", "published_at": "2025-01-01T00:00:00Z"},
                                        {"video_id": "mine", "title": "Mine", "published_at": "2026-01-01T00:00:00Z"}], at=5)
        self.assertEqual(self.store.tracked_video_ids(), ["mine", "old"])
        self.assertEqual(self.store.channel_videos(), [{"video_id": "old", "title": "Old", "published_at": "2025-01-01T00:00:00Z", "seen_at": 5},
                                                       {"video_id": "mine", "title": "Mine", "published_at": "2026-01-01T00:00:00Z", "seen_at": 5}])

    def test_a_video_no_longer_on_the_channel_is_dropped_from_the_list(self):
        self.store.save_channel_videos([{"video_id": "a", "title": "A", "published_at": "2025-01-01T00:00:00Z"}], at=1)
        self.store.save_channel_videos([{"video_id": "b", "title": "B", "published_at": "2025-02-01T00:00:00Z"}], at=2)
        self.assertEqual([v["video_id"] for v in self.store.channel_videos()], ["b"])


class PullingTheChannel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = Store(root / "b.db")
        self.client = root / "client.json"
        self.client.write_text(json.dumps({"installed": CLIENT}))
        self.now = 1_700_000_000.0
        self.store.set_setting(yt.TOKEN_KEY, {"access_token": "at", "refresh_token": "rt", "expires_at": 9e9, "scope": f"{yt.UPLOAD_SCOPE} {yt.READ_SCOPE}"})

    def puller(self, *results):
        self.run = Recorder(*results)
        return VideoStats(self.store, self.client, run=self.run, clock=lambda: self.now)

    def counts(self, *ids):
        return reply(200, {"items": [{"id": i, "statistics": {"viewCount": "5"}} for i in ids]})

    def test_the_channel_is_listed_before_the_counts_so_its_videos_are_counted_too(self):
        puller = self.puller(channel(), page(("c1", "On the channel", "2026-01-01T00:00:00Z")), self.counts("c1"))
        self.assertTrue(puller.stale())
        puller.refresh()
        self.assertEqual(len(self.run.calls), 3)
        self.assertIn("id=c1", self.run.calls[2][1])
        self.assertEqual(self.store.video_stats()["c1"]["views"], 5)
        self.assertEqual(puller.status()["message"], "")
        self.assertFalse(puller.stale())

    def test_the_channel_is_listed_once_a_day(self):
        puller = self.puller(channel(), page(("c1", "x", "2026-01-01T00:00:00Z")), self.counts("c1"), self.counts("c1"),
                             channel(), page(("c1", "x", "2026-01-01T00:00:00Z"), ("c2", "y", "2026-02-01T00:00:00Z")), self.counts("c1", "c2"))
        puller.refresh()
        self.now += 3601
        puller.refresh()
        self.assertEqual(len(self.run.calls), 4, "an hour later only the counts are read")
        self.now += CHANNEL_FRESH_FOR
        puller.refresh()
        self.assertEqual(len(self.run.calls), 7)
        self.assertEqual(sorted(self.store.video_stats()), ["c1", "c2"])

    def test_a_failed_listing_still_counts_the_known_videos_and_says_why(self):
        self.store.finish_upload(self.store.add_upload("s", "t", "private"), "mine")
        puller = self.puller(yt.CurlResult(7, "", "curl: (7) Failed to connect"), self.counts("mine"))
        puller.refresh()
        self.assertEqual(self.store.video_stats()["mine"]["views"], 5)
        self.assertIn("Failed to connect", puller.status()["message"])


if __name__ == "__main__":
    unittest.main()
