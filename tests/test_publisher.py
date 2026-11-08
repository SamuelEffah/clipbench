import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import youtube as yt  # noqa: E402
from publisher import Publisher  # noqa: E402
from store import Store  # noqa: E402


class FakeCurl:
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, args, stdin=None, on_stderr=None):
        self.calls.append((args, stdin))
        if on_stderr:
            on_stderr("## 60.0%")
        # A call nothing was queued for, such as the channel lookup after connecting, fails like a lost connection.
        return self.results.pop(0) if self.results else yt.CurlResult(7, "", "curl: (7) Failed to connect")


def ok(stdout=""):
    return yt.CurlResult(0, stdout, "")


def channel():
    """YouTube's answer to the channel lookup that follows connecting."""
    return ok(json.dumps({"items": [{"snippet": {"title": "example", "customUrl": "@example"}}]}) + "\n__HTTP__200")


class PublisherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "b.db")
        self.client = self.root / "client.json"
        self.client.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "sec"}}))
        self.video = self.root / "video.mp4"
        self.video.write_bytes(b"v" * 100)
        self.clock = [1000.0]

    def make(self, *results):
        self.curl = FakeCurl(*results)
        return Publisher(self.store, self.client, run=self.curl, clock=lambda: self.clock[0])

    def connect(self, pub):
        url = pub.begin_connect(8765)
        state = parse_qs(urlparse(url).query)["state"][0]
        return state

    def test_status_when_client_file_is_missing(self):
        pub = Publisher(self.store, self.root / "none.json", run=FakeCurl())
        status = pub.status()
        self.assertFalse(status["configured"])
        self.assertIn("youtube_client.json", status["message"])

    def test_status_progression(self):
        pub = self.make(ok(json.dumps({"access_token": "a", "refresh_token": "r", "expires_in": 3600})))
        self.assertEqual((pub.status()["configured"], pub.status()["connected"]), (True, False))
        state = self.connect(pub)
        pub.finish_connect(8765, {"code": ["c"], "state": [state]})
        self.assertTrue(pub.status()["connected"])
        pub.disconnect()
        self.assertFalse(pub.status()["connected"])

    def test_callback_with_wrong_state_is_refused(self):
        pub = self.make()
        self.connect(pub)
        with self.assertRaises(yt.YouTubeError):
            pub.finish_connect(8765, {"code": ["c"], "state": ["forged"]})
        self.assertEqual(self.curl.calls, [])

    def test_state_is_single_use_and_expires(self):
        pub = self.make(ok(json.dumps({"access_token": "a", "refresh_token": "r", "expires_in": 3600})))
        state = self.connect(pub)
        self.clock[0] += 3600
        with self.assertRaises(yt.YouTubeError):
            pub.finish_connect(8765, {"code": ["c"], "state": [state]})

    def test_denied_consent_is_reported(self):
        pub = self.make()
        self.connect(pub)
        with self.assertRaises(yt.YouTubeError) as cm:
            pub.finish_connect(8765, {"error": ["access_denied"]})
        self.assertIn("not granted", str(cm.exception))

    def test_upload_records_success(self):
        pub = self.make(
            ok(json.dumps({"access_token": "a", "refresh_token": "r", "expires_in": 3600})), channel(),
            ok("HTTP/2 200\r\nlocation: https://up/1\r\n\r\n"),
            ok(json.dumps({"id": "vid9"}) + "\n__HTTP__200"))
        pub.finish_connect(8765, {"code": ["c"], "state": [self.connect(pub)]})
        pub.start_upload("003_x", self.video, "Title #shorts", "Desc")
        pub.wait("003_x")
        state = pub.state("003_x")
        self.assertEqual((state["state"], state["video_id"]), ("done", "vid9"))
        self.assertEqual(state["studio_url"], "https://studio.youtube.com/video/vid9/edit")

    def test_upload_failure_is_recorded_and_visible(self):
        pub = self.make(
            ok(json.dumps({"access_token": "a", "refresh_token": "r", "expires_in": 3600})), channel(),
            ok('HTTP/2 403\r\n\r\n{"error":{"errors":[{"reason":"quotaExceeded"}]}}'))
        pub.finish_connect(8765, {"code": ["c"], "state": [self.connect(pub)]})
        pub.start_upload("s", self.video, "T", "D")
        pub.wait("s")
        state = pub.state("s")
        self.assertEqual(state["state"], "error")
        self.assertIn("quota", state["message"].lower())

    def test_rejected_token_during_upload_disconnects(self):
        pub = self.make(
            ok(json.dumps({"access_token": "a", "refresh_token": "r", "expires_in": 3600})), channel(),
            ok("HTTP/2 401\r\n\r\n{}"))
        pub.finish_connect(8765, {"code": ["c"], "state": [self.connect(pub)]})
        pub.start_upload("s", self.video, "T", "D")
        pub.wait("s")
        self.assertEqual(pub.state("s")["state"], "error")
        self.assertFalse(pub.status()["connected"])

    def test_upload_needs_connection_and_a_title(self):
        pub = self.make()
        with self.assertRaises(yt.YouTubeAuthError):
            pub.start_upload("s", self.video, "T", "D")
        pub = self.make(ok(json.dumps({"access_token": "a", "refresh_token": "r", "expires_in": 3600})))
        pub.finish_connect(8765, {"code": ["c"], "state": [self.connect(pub)]})
        with self.assertRaises(yt.YouTubeError):
            pub.start_upload("s", self.video, "  ", "D")
        with self.assertRaises(yt.YouTubeError):
            pub.start_upload("s", self.root / "gone.mp4", "T", "D")

    def test_state_of_unknown_short(self):
        self.assertEqual(self.make().state("nope"), {"state": "none"})


if __name__ == "__main__":
    unittest.main()
