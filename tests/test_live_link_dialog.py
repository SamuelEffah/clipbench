"""Connecting a stream belongs in a dialog, not above the source monitor."""
import json
from pathlib import Path
import subprocess
import unittest

UI = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'


class LiveLinkDialog(unittest.TestCase):
    def test_dialog_controls_preserve_current_stream_until_submit(self):
        source = (UI / 'live.js').read_text()
        handlers = source[source.index('function showLiveDialog()'):source.index('liveEl("liveIn").onclick')]
        harness = r'''
const assert=require('assert'),vm=require('vm');
const nodes=new Map();let running=false,loaded=0,entered=0,left=0;
const liveEl=id=>{if(!nodes.has(id))nodes.set(id,{value:'',hidden:false,open:false,focus(){},showModal(){this.open=true;},close(){this.open=false;}});return nodes.get(id);};
const context={liveEl,live:{resume:''},streaming:()=>running,liveSource:value=>value.startsWith('https://www.youtube.com/watch?v=')?{}:null,enterLive(){entered++;running=true;},openLive(){loaded++;},leaveLive(permanent){assert(permanent);left++;running=false;},backToStream(){},jumpToLive(){},liveClip(){},quick(){}};
vm.runInNewContext(SOURCE,context);
liveEl('liveBtn').onclick();assert(liveEl('liveDialog').open);assert(liveEl('liveEnd').hidden);assert.equal(entered,0);
liveEl('liveClose').onclick();assert(!liveEl('liveDialog').open);assert.equal(left,0);
liveEl('liveBar').onsubmit({preventDefault(){}});assert(liveEl('liveDialog').open);assert(!liveEl('liveDialogStatus').hidden);assert.equal(loaded,0);
liveEl('liveUrl').value='https://www.youtube.com/watch?v=example';liveEl('liveBar').onsubmit({preventDefault(){}});assert(!liveEl('liveDialog').open);assert.equal(entered,1);assert.equal(loaded,1);
liveEl('liveBtn').onclick();assert(!liveEl('liveEnd').hidden);assert.equal(left,0);liveEl('liveClose').onclick();assert.equal(left,0);assert(running);
liveEl('liveBtn').onclick();liveEl('liveEnd').onclick();assert.equal(left,1);assert.equal(liveEl('liveUrl').value,'');assert(!liveEl('liveDialog').open);
context.live.resume='https://www.youtube.com/watch?v=saved';liveEl('liveBtn').onclick();assert.equal(liveEl('liveUrl').value,context.live.resume);assert(!liveEl('liveEnd').hidden);
console.log('Stream dialog behavior passed');
'''
        result = subprocess.run(['node', '-e', 'const SOURCE=' + json.dumps(handlers) + ';\n' + harness], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Stream dialog behavior passed', result.stdout)

    def test_link_form_is_outside_source_monitor(self):
        html = (UI / 'index.html').read_text()
        monitor = html[html.index('<section class="mon srcmon"'):]
        monitor = monitor[:monitor.index('</section>')]
        self.assertNotIn('id="liveBar"', monitor)
        dialog = html[html.index('<dialog id="liveDialog"'):]
        dialog = dialog[:dialog.index('</dialog>')]
        self.assertIn('id="liveBar"', dialog)
        self.assertIn('id="liveUrl"', dialog)
