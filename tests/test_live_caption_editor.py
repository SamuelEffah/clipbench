import shutil
import subprocess
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "scripts" / "clipper_ui"

PRELUDE = r'''
const assert = require('assert');
const field = {blurred: 0, blur() { this.blurred++; }, onkeydown: null};
const $ = id => { assert.equal(id, "lcText"); return field; };
const key = (k, extra = {}) => { const e = {key: k, stopped: 0, prevented: 0, stopPropagation() { this.stopped++; }, preventDefault() { this.prevented++; }, target: field, ...extra}; field.onkeydown(e); return e; };
'''


@unittest.skipUnless(shutil.which("node"), "Node required")
class CaptionEditorKeys(unittest.TestCase):
    def run_js(self, body):
        source = (UI / "livecap.js").read_text()
        block = source[source.index('$("lcText").onkeydown'):]
        block = block[:block.index("\n};\n") + 4]
        result = subprocess.run(["node", "-e", PRELUDE + block + body], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_enter_finishes_the_edit_instead_of_adding_a_line(self):
        self.run_js(r'''
const e = key("Enter");
assert.equal(field.blurred, 1);
assert.equal(e.prevented, 1);
''')

    def test_escape_finishes_too_and_other_keys_stay_in_the_field(self):
        self.run_js(r'''
key("Escape");
assert.equal(field.blurred, 1);
const a = key("a", {metaKey: true});
assert.equal(a.prevented, 0, "select all is left to the field");
assert.equal(a.stopped, 1, "the editor's keys never reach the editor shortcuts");
assert.equal(field.blurred, 1);
''')


if __name__ == "__main__":
    unittest.main()
