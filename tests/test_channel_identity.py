"""The watermark and the title card carry the connected channel's name and handle, never a name written into the code."""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import clipper  # noqa: E402
import youtube as yt  # noqa: E402
from publisher import Publisher, CHANNEL_RETRY  # noqa: E402
from store import Store  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "scripts" / "clipper_ui"
CHANNEL = {"name": "example", "handle": "@example"}


def reply(status, body):
    return yt.CurlResult(0, json.dumps(body) + yt.HTTP_MARK + str(status), "")


def channel_reply(title="example", custom_url="@example"):
    snippet = {"title": title}
    if custom_url is not None:
        snippet["customUrl"] = custom_url
    return reply(200, {"items": [{"id": "UCabc", "snippet": snippet}]})


def tokens():
    return yt.CurlResult(0, json.dumps({"access_token": "a", "refresh_token": "r", "expires_in": 3600}), "")


class Recorder:
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, args, stdin=None, on_stderr=None):
        self.calls.append((args, stdin))
        return self.results.pop(0) if self.results else yt.CurlResult(7, "", "curl: (7) Failed to connect")


class AskingYouTubeWhoTheChannelIs(unittest.TestCase):
    def test_the_channel_s_name_and_handle_come_from_its_snippet(self):
        run = Recorder(channel_reply("Example Clips", "@example"))
        self.assertEqual(yt.channel_identity("tok", run), {"name": "Example Clips", "handle": "@example"})
        self.assertIn("part=snippet", run.calls[0][1])
        self.assertIn("mine=true", run.calls[0][1])

    def test_a_channel_without_a_handle_has_a_name_only(self):
        self.assertEqual(yt.channel_identity("tok", Recorder(channel_reply("Someone", None))), {"name": "Someone", "handle": ""})
        self.assertEqual(yt.channel_identity("tok", Recorder(reply(200, {"items": []}))), {})


class RememberingTheChannel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = Store(root / "b.db")
        self.client = root / "client.json"
        self.client.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "sec"}}))
        self.clock = [1000.0]

    def make(self, *results):
        self.curl = Recorder(*results)
        return Publisher(self.store, self.client, run=self.curl, clock=lambda: self.clock[0])

    def connect(self, pub):
        state = parse_qs(urlparse(pub.begin_connect(8765)).query)["state"][0]
        pub.finish_connect(8765, {"code": ["c"], "state": [state]})

    def test_connecting_learns_the_channel_and_status_carries_it(self):
        pub = self.make(tokens(), channel_reply())
        self.assertEqual(pub.status()["channel"], {})
        self.connect(pub)
        self.assertEqual(pub.status()["channel"], CHANNEL)
        self.assertEqual(pub.channel(), CHANNEL)
        self.assertEqual(len(self.curl.calls), 2, "the answer is kept, not asked for again")
        pub.disconnect()
        self.assertEqual(pub.status()["channel"], {})

    def test_a_failed_lookup_does_not_stop_the_connection_and_is_tried_again_later(self):
        pub = self.make(tokens())
        self.connect(pub)
        self.assertTrue(pub.status()["connected"])
        self.assertEqual(pub.status()["channel"], {})
        self.curl.results.append(channel_reply())
        self.assertEqual(pub.channel(), {}, "not asked again straight away")
        self.clock[0] += CHANNEL_RETRY + 1
        self.assertEqual(pub.channel(), CHANNEL)

    def test_a_channel_connected_before_this_existed_is_looked_up_on_first_use(self):
        self.store.set_setting(yt.TOKEN_KEY, {"access_token": "a", "refresh_token": "r", "expires_at": 9999.0})
        pub = self.make(channel_reply())
        self.assertEqual(pub.status()["channel"], CHANNEL)


class RenderingWithTheChannel(unittest.TestCase):
    def flags(self, project, channel):
        with mock.patch.object(clipper, "publisher", mock.Mock(channel=lambda: channel)):
            return clipper.render_flags(project)

    def test_the_watermark_and_card_use_the_connected_channel(self):
        got = self.flags({"watermark": True, "layout": "profile"}, CHANNEL)
        self.assertEqual(got[got.index("--watermark") + 1], "@example")
        self.assertEqual(got[got.index("--handle") + 1], "@example")
        self.assertEqual(got[got.index("--name") + 1], "example")

    def test_no_channel_means_no_watermark_and_a_card_without_a_name(self):
        got = self.flags({"watermark": True, "layout": "profile"}, {})
        for flag in ("--watermark", "--handle", "--name"):
            self.assertNotIn(flag, got)
        self.assertNotIn("--watermark", self.flags({"watermark": False}, CHANNEL))

    def test_nothing_in_the_code_names_a_channel(self):
        # The renderer's card starts blank and the page's card and labels are filled from the connection, so a clone of
        # this repository shows whoever connects their channel, not whoever wrote the code.
        renderer = (ROOT / "scripts" / "make_short.py").read_text()
        self.assertIn('p.add_argument("--name", default=""', renderer)
        self.assertIn('p.add_argument("--handle", default=""', renderer)
        page = (UI / "index.html").read_text()
        self.assertIn('<div id="cName"></div>', page)
        self.assertIn('<div id="cHandle"></div>', page)
        self.assertEqual(page.count('class="wmHandle"'), 2)
        self.assertNotRegex((ROOT / "scripts" / "clipper.py").read_text(), r"WATERMARK_TEXT|--watermark\", \"@")
        self.assertNotRegex((UI / "app.js").read_text(), r"fillText\(\"@")


@unittest.skipUnless(shutil.which("node"), "Node required")
class ShowingTheChannelInTheEditor(unittest.TestCase):
    def test_the_card_and_the_watermark_labels_follow_the_channel(self):
        source = (UI / "app.js").read_text()
        paint = "function paintChannel(" + source.split("function paintChannel(", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
        script = r'''
const assert = require("node:assert/strict");
const els = {cName: {textContent: "x"}, cHandle: {textContent: "x"}};
const labels = [{textContent: "x"}, {textContent: "x"}];
const $ = id => els[id];
const document = {querySelectorAll: sel => sel === ".wmHandle" ? labels : []};
const state = {channel: {name: "Example Clips", handle: "@example"}};
''' + paint + r'''
paintChannel();
assert.equal(els.cName.textContent, "Example Clips");
assert.equal(els.cHandle.textContent, "@example");
assert.ok(labels.every(l => l.textContent === "@example"));
state.channel = {};
paintChannel();
assert.equal(els.cName.textContent, "");
assert.equal(els.cHandle.textContent, "");
assert.ok(labels.every(l => /connect YouTube/i.test(l.textContent)), labels[0].textContent);
'''
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_the_preview_draws_the_channel_handle_not_a_fixed_one(self):
        source = (UI / "app.js").read_text()
        block = source.split("if (clip && state.project.watermark !== false", 1)[1].split("mctx.shadowColor = \"transparent\"", 1)[0]
        self.assertIn("state.channel", block)
        self.assertNotIn("example", block)
        self.assertRegex(source, r"watermark !== false && state\.channel\.handle")


if __name__ == "__main__":
    unittest.main()
