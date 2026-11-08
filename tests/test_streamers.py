import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import streamers


class Normalize(unittest.TestCase):
    def test_a_handle_becomes_a_channel(self):
        self.assertEqual(streamers.normalize("@LofiGirl"), {"name": "LofiGirl", "url": "https://www.youtube.com/@LofiGirl"})

    def test_a_handle_without_the_at(self):
        self.assertEqual(streamers.normalize("LofiGirl")["url"], "https://www.youtube.com/@LofiGirl")

    def test_a_channel_link_keeps_its_handle(self):
        got = streamers.normalize("https://www.youtube.com/@Google/videos?x=1")
        self.assertEqual(got, {"name": "Google", "url": "https://www.youtube.com/@Google"})

    def test_a_channel_id_link(self):
        got = streamers.normalize("youtube.com/channel/UCabcdefghij_123456-xyz")
        self.assertEqual(got["url"], "https://www.youtube.com/channel/UCabcdefghij_123456-xyz")

    def test_other_sites_and_junk_are_refused(self):
        for bad in ["", "   ", "https://kick.com/someone", "https://example.com/@x", "two words", "@" + "a" * 80]:
            with self.assertRaises(ValueError, msg=bad):
                streamers.normalize(bad)


class TwitchChannels(unittest.TestCase):
    def test_a_twitch_link(self):
        self.assertEqual(streamers.normalize("https://www.twitch.tv/Jynxzi"), {"name": "Jynxzi", "url": "https://www.twitch.tv/jynxzi"})

    def test_without_the_scheme_and_with_a_path(self):
        self.assertEqual(streamers.normalize("twitch.tv/shroud/videos?filter=all")["url"], "https://www.twitch.tv/shroud")

    def test_pages_that_are_not_channels_are_refused(self):
        for bad in ["https://www.twitch.tv/videos/123456", "https://www.twitch.tv/directory", "https://www.twitch.tv/", "https://www.twitch.tv/a"]:
            with self.assertRaises(ValueError, msg=bad):
                streamers.normalize(bad)

    def test_the_kind_comes_from_the_link_and_is_in_every_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "streamers.json"
            self.assertEqual([s["kind"] for s in streamers.add(path, "twitch.tv/shroud")], ["twitch"])
            self.assertEqual([s["kind"] for s in streamers.add(path, "@Google")], ["twitch", "youtube"])
            self.assertEqual([s["kind"] for s in streamers.remove(path, "https://www.youtube.com/@x")], ["twitch", "youtube"])


class Storage(unittest.TestCase):
    def test_add_remove_and_no_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "streamers.json"
            self.assertEqual(streamers.load(path), [])
            one = streamers.add(path, "@Google")
            self.assertEqual(len(one), 1)
            self.assertEqual(len(streamers.add(path, "https://www.youtube.com/@google")), 1)
            self.assertEqual(streamers.remove(path, "https://www.youtube.com/@Google"), [])

    def test_a_damaged_file_reads_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "streamers.json"
            path.write_text("{not json")
            self.assertEqual(streamers.load(path), [])

    def test_load_ignores_entries_that_are_not_channels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "streamers.json"
            path.write_text(json.dumps([{"name": "a", "url": "https://evil.test/x"}, {"name": "ok", "url": "https://www.youtube.com/@ok"}]))
            self.assertEqual([s["name"] for s in streamers.load(path)], ["ok"])


def fake(stdout="", stderr="", code=0):
    return mock.Mock(return_value=subprocess.CompletedProcess([], code, stdout, stderr))


class CheckTwitch(unittest.TestCase):
    URL = "https://www.twitch.tv/jynxzi"

    def test_live_watches_the_channel_page_and_uses_the_stream_title(self):
        with mock.patch("subprocess.run", fake("True|320700397406|[648/730] PLAYING FORTNITE\n")):
            self.assertEqual(streamers.check_live("yt-dlp", self.URL),
                             {"live": True, "title": "[648/730] PLAYING FORTNITE", "watch": self.URL})

    def test_asks_for_the_channel_page_itself(self):
        run = fake("False|x|y")
        with mock.patch("subprocess.run", run):
            streamers.check_live("yt-dlp", self.URL)
        self.assertEqual(run.call_args.args[0][-1], self.URL)

    def test_offline(self):
        with mock.patch("subprocess.run", fake(stderr="ERROR: [twitch:stream] jynxzi: The channel is not currently live", code=1)):
            self.assertEqual(streamers.check_live("yt-dlp", self.URL), {"live": False})

    def test_a_channel_that_does_not_exist_is_unknown(self):
        with mock.patch("subprocess.run", fake(stderr="ERROR: [twitch:stream] zz: zz does not exist", code=1)):
            with self.assertRaises(ValueError):
                streamers.check_live("yt-dlp", self.URL)


class CheckLive(unittest.TestCase):
    URL = "https://www.youtube.com/@Google"

    def test_live(self):
        with mock.patch("subprocess.run", fake("True|abc123XYZ_-|Big stream\n")):
            self.assertEqual(streamers.check_live("yt-dlp", self.URL),
                             {"live": True, "title": "Big stream", "watch": "https://www.youtube.com/watch?v=abc123XYZ_-"})

    def test_asks_for_the_live_page_of_the_channel(self):
        run = fake("False|x|y")
        with mock.patch("subprocess.run", run):
            streamers.check_live("yt-dlp", self.URL)
        self.assertEqual(run.call_args.args[0][-1], self.URL + "/live")

    def test_not_live(self):
        with mock.patch("subprocess.run", fake(stderr="ERROR: [youtube:tab] @Google: The channel is not currently live", code=1)):
            self.assertEqual(streamers.check_live("yt-dlp", self.URL), {"live": False})

    def test_a_finished_stream_is_not_live(self):
        with mock.patch("subprocess.run", fake("False|abc123XYZ_-|Old stream")):
            self.assertEqual(streamers.check_live("yt-dlp", self.URL), {"live": False})

    def test_any_other_failure_is_unknown_not_offline(self):
        with mock.patch("subprocess.run", fake(stderr="ERROR: unable to download webpage", code=1)):
            with self.assertRaises(ValueError):
                streamers.check_live("yt-dlp", self.URL)

    def test_a_hung_check_is_unknown(self):
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("yt-dlp", 40)):
            with self.assertRaises(ValueError):
                streamers.check_live("yt-dlp", self.URL)


class Calls(unittest.TestCase):
    def setUp(self):
        import clipper
        self.clipper = clipper
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(clipper, "STREAMER_FILE", Path(self.tmp.name) / "streamers.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_add_then_check_a_saved_channel(self):
        got, status = self.clipper.streamer_call("/api/streamers", {"input": "@Google"})
        self.assertEqual((status, got[0]["name"]), (200, "Google"))
        with mock.patch("shutil.which", return_value="yt-dlp"), mock.patch("subprocess.run", fake("True|abc123XYZ_-|Hi")):
            got, status = self.clipper.streamer_call("/api/streamers/live", {"url": "https://www.youtube.com/@Google"})
        self.assertEqual((status, got["live"]), (200, True))

    def test_only_saved_channels_are_checked(self):
        got, status = self.clipper.streamer_call("/api/streamers/live", {"url": "https://www.youtube.com/@Nobody"})
        self.assertEqual(status, 400)

    def test_a_bad_link_is_a_400_with_a_message(self):
        got, status = self.clipper.streamer_call("/api/streamers", {"input": "https://kick.com/x"})
        self.assertEqual((status, "YouTube" in got["error"]), (400, True))


if __name__ == "__main__":
    unittest.main()
