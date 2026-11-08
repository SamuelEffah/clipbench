import shutil
import subprocess
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "scripts" / "clipper_ui"

PRELUDE = r'''
const assert = require('assert');
const timers = [];
const setTimeout = (fn, ms) => { timers.push([fn, ms]); return timers.length; };
const clearTimeout = () => {};
const el = {textContent: "", title: "", className: "saved", onclick: null,
  classList: {contains(c) { return el.className.split(" ").includes(c); }}};
const retry = () => {};
'''


@unittest.skipUnless(shutil.which("node"), "Node required")
class SavePill(unittest.TestCase):
    def run_js(self, body):
        source = (UI / "app.js").read_text().split("const SAVE_STATES", 1)[1].split("\n}\n", 1)[0]
        result = subprocess.run(["node", "-e", PRELUDE + "const SAVE_STATES" + source + "\n}\n" + body], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_offline_warns_in_words_that_say_the_edits_are_safe_and_offers_a_retry(self):
        self.run_js(r'''
assert.equal(paintSaveState(el, "offline", retry), "offline");
assert.equal(el.textContent, "Offline");
assert.equal(el.className, "saved bad");
assert.equal(el.onclick, retry);
assert.ok(el.title.includes("Click to try now"));
paintSaveState(el, "failed", retry);
assert.equal(el.textContent, "Not saved");
assert.equal(el.className, "saved bad");
''')

    def test_a_save_after_trouble_says_so_in_green_for_a_moment_then_hides(self):
        self.run_js(r'''
paintSaveState(el, "offline", retry);
assert.equal(paintSaveState(el, "saved"), "back");
assert.equal(el.textContent, "Saved");
assert.equal(el.className, "saved good");
assert.equal(el.onclick, null);
assert.equal(timers.length, 1); assert.equal(timers[0][1], BACK_FOR);
timers[0][0]();
assert.equal(el.className, "saved");
''')

    def test_a_plain_save_stays_quiet(self):
        self.run_js(r'''
assert.equal(paintSaveState(el, "saved"), "saved");
assert.equal(el.textContent, "Saved");
assert.equal(el.className, "saved");
assert.equal(timers.length, 0);
''')


if __name__ == "__main__":
    unittest.main()
