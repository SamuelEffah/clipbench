import base64
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import youtube as yt  # noqa: E402
from store import Store  # noqa: E402

CLIENT = {"client_id": "cid.apps.googleusercontent.com", "client_secret": "s3cret"}


def result(stdout="", code=0, stderr=""):
    return yt.CurlResult(code, stdout, stderr)


class Recorder:
    """A fake curl: returns queued results and remembers what it was given."""

    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, args, stdin=None, on_stderr=None):
        self.calls.append((args, stdin))
        if on_stderr:
            on_stderr("#### 50.0%\r######## 100.0%")
        return self.results.pop(0)


class ClientFileTest(unittest.TestCase):
    def write(self, data):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = Path(d.name) / "client.json"
        p.write_text(data if isinstance(data, str) else json.dumps(data))
        return p

    def test_reads_desktop_client_file(self):
        p = self.write({"installed": {"client_id": "a", "client_secret": "b"}})
        self.assertEqual(yt.load_client(p), {"client_id": "a", "client_secret": "b"})

    def test_missing_file_explains_where_to_put_it(self):
        with self.assertRaises(yt.YouTubeError) as cm:
            yt.load_client(Path("/nope/client.json"))
        self.assertIn("youtube_client.json", str(cm.exception))

    def test_web_client_type_is_rejected(self):
        p = self.write({"web": {"client_id": "a", "client_secret": "b"}})
        with self.assertRaises(yt.YouTubeError) as cm:
            yt.load_client(p)
        self.assertIn("Desktop", str(cm.exception))

    def test_garbage_is_rejected(self):
        with self.assertRaises(yt.YouTubeError):
            yt.load_client(self.write("not json"))


class AuthUrlTest(unittest.TestCase):
    def test_pkce_challenge_matches_verifier(self):
        verifier, challenge = yt.new_pkce()
        digest = hashlib.sha256(verifier.encode()).digest()
        self.assertEqual(challenge, base64.urlsafe_b64encode(digest).rstrip(b"=").decode())
        self.assertGreaterEqual(len(verifier), 43)

    def test_auth_url_has_scope_state_and_offline_access(self):
        url = yt.auth_url(CLIENT, "http://127.0.0.1:8765/api/youtube/callback", "st", "ch")
        q = parse_qs(urlparse(url).query)
        self.assertEqual(q["client_id"], [CLIENT["client_id"]])
        self.assertEqual(q["scope"], [yt.SCOPE])
        self.assertIn("youtube.upload", yt.SCOPE)
        self.assertEqual((q["state"], q["code_challenge"], q["access_type"]), (["st"], ["ch"], ["offline"]))
        self.assertEqual(q["code_challenge_method"], ["S256"])
        self.assertNotIn("s3cret", url)


class TokenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "b.db")

    def test_exchange_code_keeps_secret_out_of_argv(self):
        run = Recorder(result(json.dumps({"access_token": "at", "refresh_token": "rt", "expires_in": 3600})))
        tokens = yt.exchange_code(CLIENT, "code1", "ver", "http://127.0.0.1:1/cb", run, now=1000)
        self.assertEqual(tokens, {"access_token": "at", "refresh_token": "rt", "expires_at": 4600, "scope": yt.SCOPE})
        args, stdin = run.calls[0]
        self.assertNotIn("s3cret", " ".join(args))
        self.assertIn("s3cret", stdin)
        self.assertIn("code_verifier=ver", stdin)

    def test_exchange_failure_is_readable(self):
        run = Recorder(result(json.dumps({"error": "invalid_grant", "error_description": "Bad code"})))
        with self.assertRaises(yt.YouTubeError) as cm:
            yt.exchange_code(CLIENT, "c", "v", "http://x", run)
        self.assertIn("Bad code", str(cm.exception))

    def test_valid_token_is_reused(self):
        self.store.set_setting(yt.TOKEN_KEY, {"access_token": "at", "refresh_token": "rt", "expires_at": 5000})
        run = Recorder()
        self.assertEqual(yt.access_token(self.store, CLIENT, run, now=1000), "at")
        self.assertEqual(run.calls, [])

    def test_expired_token_is_refreshed_and_saved(self):
        self.store.set_setting(yt.TOKEN_KEY, {"access_token": "old", "refresh_token": "rt", "expires_at": 1000})
        run = Recorder(result(json.dumps({"access_token": "new", "expires_in": 3600})))
        self.assertEqual(yt.access_token(self.store, CLIENT, run, now=2000), "new")
        saved = self.store.get_setting(yt.TOKEN_KEY)
        self.assertEqual((saved["access_token"], saved["refresh_token"], saved["expires_at"]), ("new", "rt", 5600))

    def test_revoked_refresh_token_disconnects(self):
        self.store.set_setting(yt.TOKEN_KEY, {"access_token": "old", "refresh_token": "rt", "expires_at": 0})
        run = Recorder(result(json.dumps({"error": "invalid_grant"})))
        with self.assertRaises(yt.YouTubeAuthError):
            yt.access_token(self.store, CLIENT, run, now=10)
        self.assertIsNone(self.store.get_setting(yt.TOKEN_KEY))

    def test_not_connected(self):
        with self.assertRaises(yt.YouTubeAuthError):
            yt.access_token(self.store, CLIENT, Recorder(), now=0)


class UploadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.video = Path(self.tmp.name) / "video.mp4"
        self.video.write_bytes(b"x" * 2048)

    def start_reply(self, location="https://upload.example/session1", status="HTTP/2 200"):
        return result(f"{status}\r\nlocation: {location}\r\ncontent-length: 0\r\n\r\n")

    def test_upload_sends_unlisted_metadata_then_file(self):
        run = Recorder(self.start_reply(), result(json.dumps({"id": "vid42"}) + "\n__HTTP__200"))
        seen = []
        uploaded = yt.upload_video("ZZtokZZ", self.video, "My title #shorts", "Desc", run, seen.append)
        self.assertEqual((uploaded.video_id, uploaded.privacy), ("vid42", "unlisted"))
        first_args, first_stdin = run.calls[0]
        self.assertIn("Bearer ZZtokZZ", first_stdin)
        self.assertIn("privacyStatus", first_stdin)
        self.assertIn("unlisted", first_stdin)
        self.assertIn("selfDeclaredMadeForKids", first_stdin)
        self.assertIn("2048", first_stdin)
        second_args, second_stdin = run.calls[1]
        self.assertIn("https://upload.example/session1", second_stdin)
        self.assertIn(str(self.video), " ".join(second_args))
        self.assertNotIn("ZZtokZZ", " ".join(first_args + second_args))
        self.assertEqual(seen[-1], 100)

    def test_quota_error_is_friendly(self):
        body = {"error": {"code": 403, "message": "m", "errors": [{"reason": "quotaExceeded"}]}}
        run = Recorder(result("HTTP/2 403\r\ncontent-type: application/json\r\n\r\n" + json.dumps(body)))
        with self.assertRaises(yt.YouTubeError) as cm:
            yt.upload_video("ZZtokZZ", self.video, "t", "d", run, lambda p: None)
        self.assertIn("quota", str(cm.exception).lower())

    def test_expired_token_asks_to_reconnect(self):
        run = Recorder(result("HTTP/2 401\r\n\r\n{}"))
        with self.assertRaises(yt.YouTubeAuthError):
            yt.upload_video("ZZtokZZ", self.video, "t", "d", run, lambda p: None)

    def test_missing_location_header_fails(self):
        run = Recorder(result("HTTP/2 200\r\n\r\n"))
        with self.assertRaises(yt.YouTubeError):
            yt.upload_video("ZZtokZZ", self.video, "t", "d", run, lambda p: None)

    def test_curl_failure_reports_the_reason(self):
        run = Recorder(result("", code=6, stderr="curl: (6) Could not resolve host"))
        with self.assertRaises(yt.YouTubeError) as cm:
            yt.upload_video("ZZtokZZ", self.video, "t", "d", run, lambda p: None)
        self.assertIn("resolve", str(cm.exception))

    def test_config_quoting_escapes_quotes_and_backslashes(self):
        self.assertEqual(yt.config_value('a"b\\c\nd'), '"a\\"b\\\\c\\nd"')

    def test_percent_parser_takes_the_last_figure(self):
        self.assertEqual(yt.last_percent("## 12.5%\r#### 40.0%"), 40.0)
        self.assertIsNone(yt.last_percent("nothing"))

    def test_continue_block_is_skipped_when_reading_headers(self):
        status, headers, body = yt._split_response("HTTP/1.1 100 Continue\r\n\r\nHTTP/2 200\r\nLocation: https://u/1\r\n\r\n{}")
        self.assertEqual((status, headers["location"], body), (200, "https://u/1", "{}"))

    def test_studio_link(self):
        self.assertEqual(yt.studio_url("abc"), "https://studio.youtube.com/video/abc/edit")


if __name__ == "__main__":
    unittest.main()
