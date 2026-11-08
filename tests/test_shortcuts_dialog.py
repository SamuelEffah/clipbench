import json
import subprocess
import unittest
from pathlib import Path


class ShortcutsDialog(unittest.TestCase):
    def test_station_dialogs_close_cleanly_and_keep_button_state(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/shortcuts.js').read_text()
        harness = r'''
const vm=require('vm'),assert=require('assert');const nodes=new Map();
const $=id=>{if(!nodes.has(id))nodes.set(id,{id,open:false,attrs:{},events:{},closeButton:{},setAttribute(k,v){this.attrs[k]=v;},showModal(){this.open=true;},close(){this.open=false;this.events.close?.();},querySelector(){return this.closeButton;},addEventListener(k,v){this.events[k]=v;},getBoundingClientRect(){return {left:100,right:500,top:100,bottom:600};}});return nodes.get(id);};
vm.runInNewContext(SOURCE,{$});
$('helpBtn').onclick();assert($('keysPop').open);assert.equal($('helpBtn').attrs['aria-expanded'],'true');assert.equal($('helpBtn3').attrs['aria-expanded'],'true');
$('keysPop').events.click({target:$('keysPop'),clientX:120,clientY:150});assert($('keysPop').open);
$('helpBtn2').onclick();assert(!$('keysPop').open);assert($('keysShort').open);assert.equal($('helpBtn').attrs['aria-expanded'],'false');
$('keysShort').closeButton.onclick();assert(!$('keysShort').open);assert.equal($('helpBtn2').attrs['aria-expanded'],'false');
$('helpBtn3').onclick();$('keysPop').events.click({target:$('keysPop'),clientX:10,clientY:10});assert(!$('keysPop').open);
$('helpBtn').onclick();$('keysPop').close();assert.equal($('helpBtn').attrs['aria-expanded'],'false');
console.log('Shortcut modal behavior passed');
'''
        result = subprocess.run(['node', '-e', 'const SOURCE=' + json.dumps(source) + ';\n' + harness], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Shortcut modal behavior passed', result.stdout)
