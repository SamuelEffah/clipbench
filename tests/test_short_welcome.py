import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class ShortWelcome(unittest.TestCase):
    def test_empty_bank_and_populated_states_offer_the_right_next_action(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/short.js').read_text()
        helper = 'function paintShortWelcome() {' + source.split('function paintShortWelcome() {', 1)[1].split('\nfunction renderShortMode', 1)[0]
        script = r'''
const assert = require('node:assert/strict');
let short = true, bank = [];
const state = {project: {clips: []}};
const nodes = new Map();
const $ = id => {if (!nodes.has(id)) nodes.set(id,{hidden:false,disabled:false,textContent:'',classes:{},classList:{toggle(k,v){nodes.get(id).classes[k]=v;}}});return nodes.get(id);};
const inShort = () => short;
const bankOf = () => bank;
''' + helper + r'''
paintShortWelcome();
assert.equal($('shortWelcome').hidden, true);
assert.equal($('shortWelcomeChoose').hidden, true);
assert.equal($('shortWelcomeFind').classes.primary, true);
assert.equal($('thPlay').disabled, true);
bank = [{}, {}]; paintShortWelcome();
assert.equal($('shortWelcomeChoose').hidden, false);
assert.match($('shortWelcomeNote').textContent, /2 saved clips are ready/);
assert.equal($('shortWelcomeFind').classes.primary, false);
state.project.clips = [{}]; paintShortWelcome();
assert.equal($('shortWelcome').hidden, true);
assert.equal($('theater').classes['short-empty'], false);
assert.equal($('thPlay').disabled, false);
state.project.clips = []; paintShortWelcome(); assert.equal($('shortWelcome').hidden, true);
short = false; paintShortWelcome(); assert.equal($('shortWelcome').hidden, true);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
