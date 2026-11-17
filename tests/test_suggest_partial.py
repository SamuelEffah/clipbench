import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import clipper  # noqa: E402

UI = Path(__file__).resolve().parents[1] / "scripts" / "clipper_ui"


class RunningSearchHandsOverItsPartialList(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.src = self.root / "source.mp4"
        self.src.write_bytes(b"video")
        self.vid = "partial"
        self.jobs = {self.vid: {"state": "working", "pct": 0, "model": ""}}
        self.during = []

        def fake_suggest(*args, **kwargs):
            kwargs["partial"]([{"in": 1, "out": 31, "score": 0.5, "text": "a"}])
            self.during.append(dict(self.jobs[self.vid]))
            kwargs["progress"](1, 2)
            kwargs["partial"]([{"in": 40, "out": 70, "score": 0.7, "text": "b"}, {"in": 1, "out": 31, "score": 0.5, "text": "a"}])
            self.during.append(dict(self.jobs[self.vid]))
            return [{"in": 40, "out": 70, "score": 0.7, "text": "b"}]

        patches = [patch.object(clipper, "PROXY_DIR", self.root / "proxy"),
                   patch.object(clipper, "registry", {self.vid: self.src}),
                   patch.object(clipper, "suggest_jobs", self.jobs),
                   patch.object(clipper, "load_wave", return_value={}),
                   patch.object(clipper, "get_scenes", return_value={"state": "ready", "scenes": []}),
                   patch.object(clipper, "probe", return_value={"duration": 60}),
                   patch.object(clipper, "load_motion", return_value=None),
                   patch.object(clipper, "dialogue_cues", return_value=[(1.0, 3.0, "Hello there.")]),
                   patch.object(clipper.suggest, "ollama_models", return_value=["qwen3"]),
                   patch.object(clipper.suggest, "suggest", side_effect=fake_suggest)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_the_job_carries_the_best_so_far_while_it_works_and_the_final_list_when_done(self):
        clipper.run_suggest(self.vid)
        self.assertEqual([j["state"] for j in self.during], ["working", "working"])
        self.assertEqual([len(j["clips"]) for j in self.during], [1, 2])
        self.assertEqual(self.during[1]["pct"], 50)
        self.assertIn("profile", self.during[0])
        done = self.jobs[self.vid]
        self.assertEqual(done["state"], "ready")
        self.assertEqual([c["in"] for c in done["clips"]], [40])


@unittest.skipUnless(shutil.which("node"), "Node required")
class PaintingAListStillFilling(unittest.TestCase):
    def test_a_running_search_with_moments_shows_them_with_how_far_it_is(self):
        source = (UI / "suggest.js").read_text()
        paint = "const PROFILE_NOTE" + source.split("const PROFILE_NOTE", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
        script = r'''
const assert = require("node:assert/strict");
const state = {current: {id: "v", path: "/v.mp4"}, project: {clips: []}};
const box = {hidden: true, innerHTML: "", querySelector: () => ({title: "", textContent: ""}), querySelectorAll: () => []};
const $ = id => id === "suggest" ? box : {textContent: "", disabled: false, onclick: null};
const esc = s => String(s), fmt = t => String(t);
const suggestAdded = () => false, suggestClips = s => [s], playRange = () => {}, saveReview = () => {}, addKeptSuggestions = () => {};
const suggestionKey = s => `${s.in}:${s.out}`;
const suggestPieces = s => s.pieces || [[s.in, s.out]];
const paintSuggestionRange = () => {};
let suggestionPreview = null;
let suggestionReview = new Map();
let suggestion = {vid: "v", busy: true, pct: 40, model: "qwen3", profile: {kind: "speech"}, clips: [
  {in: 1, out: 31, score: 0.7, text: "a", why: "joke"}, {in: 40, out: 70, score: 0.6, text: "b"}, {in: 80, out: 110, score: 0.5, text: "c"}]};
''' + paint + r'''
paintSuggest();
assert.equal(box.hidden, false);
assert.equal((box.innerHTML.match(/class="sg sgcard"/g) || []).length, 3, "every moment scored so far is listed");
assert.match(box.innerHTML, /3 so far, 40% scored/);
assert.match(box.innerHTML, /aria-label="Preview moment 1"/);
assert.match(box.innerHTML, /aria-label="Keep moment 1"/);
assert.match(box.innerHTML, /aria-label="Skip moment 1"/);
assert.match(box.innerHTML, /class="sgreason">joke/);
suggestion = {...suggestion, clips: [{in: 1, out: 50, pieces: [[1, 11], [40, 50]], text: "joined"}]};
paintSuggest();
assert.match(box.innerHTML, /sgduration num">20s/);
assert.match(box.innerHTML, /Two moments joined/);
suggestion = {...suggestion, clips: []};
paintSuggest();
assert.match(box.innerHTML, /Looking for clips, 40%/);
assert.equal((box.innerHTML.match(/class="sg sgcard"/g) || []).length, 0);
'''
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)


if __name__ == "__main__":
    unittest.main()
