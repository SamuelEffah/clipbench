import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from store import Store  # noqa: E402
from scripts import clipper  # noqa: E402

UI = Path(__file__).resolve().parent.parent / "scripts" / "clipper_ui"
VID = "d303cbc73f4f"


class ReviewRoutes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "bench.db")
        self.patches = [mock.patch.object(clipper, "store", self.store), mock.patch.object(clipper, "registry", {VID: Path("/v/talk.mp4")})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def call(self, method, path, body=None):
        handler = object.__new__(clipper.Handler)
        handler.host_ok = handler.origin_ok = lambda: True
        handler.path = path
        handler.headers = {}
        handler.read_json = lambda: body
        result = []
        handler.send_json = lambda data, status=200: result.append((data, status))
        (handler.do_POST if method == "POST" else handler.do_GET)()
        return result[0]

    def test_a_decision_is_saved_with_the_moment_and_read_back(self):
        body = {"in": 10.5, "out": 42, "decision": "keep", "moment": {"text": "a line", "why": "joke", "parts": {"hook": 70}, "score": 0.8, "profile": "speech", "junk": "x"}}
        self.assertEqual(self.call("POST", f"/api/review/{VID}", body), ({"ok": True}, 200))
        data, status = self.call("GET", f"/api/review/{VID}")
        self.assertEqual(status, 200)
        self.assertEqual(data, {"reviews": [{"in": 10.5, "out": 42.0, "decision": "keep"}]})
        saved = self.store.suggestion_reviews(VID)[0]["moment"]
        self.assertEqual(saved, {"text": "a line", "why": "joke", "parts": {"hook": 70}, "score": 0.8, "profile": "speech"})

    def test_a_cleared_decision_removes_the_row(self):
        self.call("POST", f"/api/review/{VID}", {"in": 1, "out": 2, "decision": "skip", "moment": {}})
        self.call("POST", f"/api/review/{VID}", {"in": 1, "out": 2, "decision": None, "moment": {}})
        self.assertEqual(self.call("GET", f"/api/review/{VID}")[0], {"reviews": []})

    def test_bad_input_is_refused(self):
        self.assertEqual(self.call("POST", "/api/review/0000000000ff", {"in": 1, "out": 2, "decision": "keep", "moment": {}})[1], 400)
        self.assertEqual(self.call("GET", "/api/review/0000000000ff")[1], 400)
        self.assertEqual(self.call("POST", f"/api/review/{VID}", {"in": "x", "out": 2, "decision": "keep", "moment": {}})[1], 400)
        self.assertEqual(self.call("POST", f"/api/review/{VID}", {"in": 3, "out": 2, "decision": "keep", "moment": {}})[1], 400)
        self.assertEqual(self.call("POST", f"/api/review/{VID}", {"in": 1, "out": 2, "decision": "maybe", "moment": {}})[1], 400)
        self.assertEqual(self.call("POST", f"/api/review/{VID}", {"in": 1, "out": 2, "decision": "keep", "moment": {"text": "x" * 5000}})[1], 400)
        self.assertEqual(self.call("POST", f"/api/review/{VID}", None)[1], 400)
        self.assertEqual(self.store.suggestion_reviews(VID), [])


PRELUDE = r'''
const assert = require('assert');
const toasts = [];
const toast = m => toasts.push(m);
const calls = [];
let apiAnswer = () => ({reviews: []});
const api = async (path, method = "GET", body) => { calls.push([method, path, body]); return apiAnswer(path, body); };
'''


def run_js(body):
    return subprocess.run(["node", "-e", PRELUDE + (UI / "review.js").read_text() + body], capture_output=True, text=True)


@unittest.skipUnless(shutil.which("node"), "Node required")
class ReviewPage(unittest.TestCase):
    def check(self, body):
        result = run_js(body)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_saved_decisions_load_into_a_map_by_moment(self):
        self.check(r'''
(async () => {
  apiAnswer = () => ({reviews: [{in: 10.5, out: 42, decision: "keep"}, {in: 60, out: 90, decision: "skip"}]});
  const got = await loadReviews({id: "abc"});
  assert.deepEqual([...got.entries()], [["10.5:42", "keep"], ["60:90", "skip"]]);
  assert.deepEqual(calls, [["GET", "/api/review/abc", undefined]]);
})().catch(e => { console.error(e); process.exit(1); });
''')

    def test_a_failed_load_is_said_and_leaves_no_marks(self):
        self.check(r'''
(async () => {
  apiAnswer = () => { throw new Error("offline"); };
  const got = await loadReviews({id: "abc"});
  assert.equal(got.size, 0);
  assert.deepEqual(toasts, ["offline"]);
})().catch(e => { console.error(e); process.exit(1); });
''')

    def test_a_decision_is_sent_with_what_the_moment_looked_like(self):
        self.check(r'''
(async () => {
  const s = {in: 10.5, out: 42, text: "a line", why: "joke", parts: {hook: 70, energy: 50, words: 40}, score: 0.8, extra: 1};
  await saveReview({id: "abc"}, s, "keep", {kind: "speech"});
  assert.deepEqual(calls, [["POST", "/api/review/abc", {in: 10.5, out: 42, decision: "keep", moment: {text: "a line", why: "joke", parts: {hook: 70, energy: 50, words: 40}, score: 0.8, profile: "speech"}}]]);
  await saveReview({id: "abc"}, s, null, undefined);
  assert.equal(calls[1][2].decision, null);
  assert.equal(calls[1][2].moment.profile, undefined);
})().catch(e => { console.error(e); process.exit(1); });
''')

    def test_a_failed_save_is_said(self):
        self.check(r'''
(async () => {
  apiAnswer = () => { throw new Error("Couldn't save"); };
  await saveReview({id: "abc"}, {in: 1, out: 2}, "skip");
  assert.deepEqual(toasts, ["Couldn't save"]);
})().catch(e => { console.error(e); process.exit(1); });
''')


if __name__ == "__main__":
    unittest.main()
