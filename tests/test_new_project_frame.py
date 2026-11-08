import shutil
import subprocess
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "scripts/clipper_ui/app.js"


def slice_of(source, start, end):
    return start + source.split(start, 1)[1].split(end, 1)[0]


@unittest.skipUnless(shutil.which("node"), "Node required")
class NewProjectFrame(unittest.TestCase):
    def test_a_new_project_does_not_keep_the_last_project_s_video_on_screen(self):
        source = APP.read_text()
        create = slice_of(source, "async function createProject(", "// The copy has the same")
        drop = slice_of(source, "function dropVideo(", "\n}\n") + "\n}\n"
        script = r'''
const assert = require("node:assert/strict");
const calls = [];
const fakeVideo = () => ({src: "/media/old", dataset: {id: "old"}, pause() { calls.push("pause"); }, removeAttribute(k) { delete this[k]; calls.push("remove " + k); }, load() { calls.push("load"); }});
const video = fakeVideo(), spare = fakeVideo(), videos = [video, spare];
const els = {srcName: {textContent: "Old video"}, srcMeta: {textContent: "1080p, 9:41"}, saved: {textContent: ""}};
const $ = id => els[id] || {textContent: ""};
const state = {current: {id: "old"}, clipStop: 3, project: {name: "old"}, sel: 2, audioSel: null};
const preview = {on: false}, pbox = {value: ""};
const flushSave = async () => {}, save = async () => {}, loadAssets = async () => {}, rememberProject = () => {}, render = () => {}, resetHistory = () => {};
''' + drop + create + r'''
(async () => {
  await createProject("fresh", false);
  assert.equal(state.current, null);
  assert.equal(state.clipStop, null);
  assert.ok(!("src" in video) && !("src" in spare), "both video elements drop their source");
  assert.ok(calls.includes("load"), "the element reloads so the old frame goes");
  assert.equal(els.srcName.textContent, "No video selected");
  assert.equal(els.srcMeta.textContent, "");
  assert.equal(state.project.name, "fresh");
})().catch(e => { console.error(e); process.exitCode = 1; });
'''
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_opening_a_project_drops_the_old_video_too(self):
        source = APP.read_text()
        load = slice_of(source, "async function loadProject(", "// While streaming Enter")
        self.assertIn("dropVideo()", load)
        self.assertIn("dropVideo()", slice_of(source, "async function removeVideo(", "await refreshLibrary"))


if __name__ == "__main__":
    unittest.main()
