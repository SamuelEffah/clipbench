import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node required')
class LibraryRequestPerformance(unittest.TestCase):
    def run_js(self, filename, scenario):
        source = (ROOT / 'scripts/clipper_ui' / filename).read_text()
        source = source.replace('startStreamers();', '')
        setup = r'''
const assert=require('node:assert/strict');
const ResizeObserver=class{constructor(callback){this.callback=callback;}observe(){}};
const window={addEventListener(){}};
const nodes={}, $=id=>nodes[id]||(nodes[id]={classList:{toggle(){},contains(){return false}},setAttribute(){},addEventListener(){}});
const document={hidden:false,addEventListener(){},createElement(){return {}}};
const localStorage={getItem(){return null},setItem(){}};
const Audio=function(){this.addEventListener=()=>{}};
let live=false; const streaming=()=>live, toast=()=>{throw Error('unexpected toast')};
const calls=[],pending=[];
const api=(...args)=>{calls.push(args);return new Promise((resolve,reject)=>pending.push({resolve,reject}));};
const tick=()=>new Promise(setImmediate);
'''
        out = subprocess.run(['node', '-e', setup + source + scenario], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_streamer_sweeps_serialize_and_stop_between_channels_when_hidden(self):
        self.run_js('streamers.js', r'''
paintStreamers=()=>{};
(async()=>{
streamerState.list=[{url:'a'},{url:'b'}];
const first=checkStreamers();
for(let i=0;i<50;i++) checkStreamers();
assert.equal(calls.length,1);
document.hidden=true;pending.shift().resolve({live:false});await first;
assert.equal(calls.length,1);
document.hidden=false;const resumed=checkStreamers();
pending.shift().resolve({live:true});await tick();
assert.equal(calls.length,3);
streamerState.list=[];pending.shift().resolve({live:true});await resumed;
assert.equal(streamerState.status.b,undefined);
live=true;await checkStreamers();assert.equal(calls.length,3);
})().catch(e=>{console.error(e);process.exitCode=1});
''')

    def test_sound_search_only_runs_newest_pending_and_ignores_stale_errors(self):
        self.run_js('soundbank.js', r'''
paintSounds=()=>{};
(async()=>{
sbState.query='first';const first=loadSounds(1);
for(let i=0;i<50;i++){sbSearchVersion++;sbState.query='q'+i;loadSounds(1)}
assert.equal(calls.length,1);
pending.shift().reject(Error('stale'));await tick();
assert.equal(calls.length,2);assert(calls[1][0].includes('q49'));
pending.shift().resolve({total:2,sounds:[{file:'latest'}]});await first;
assert.equal(sbState.sounds[0].file,'latest');assert.equal(sbState.busy,false);
const page=loadSounds(2);pending.shift().resolve({total:2,sounds:[{file:'more'}]});await page;
assert.equal(sbState.sounds.length,2);
})().catch(e=>{console.error(e);process.exitCode=1});
''')

    def test_sound_playback_rebuilds_only_affected_rows(self):
        self.run_js('soundbank.js', r'''
let created=0,replaced=0;
const list={children:[],replaceChildren(...rows){this.children=rows;replaced++}};
nodes.sbList=list;
sbRow=s=>{created++;return {file:s.file}};
sbState.sounds=Array.from({length:1000},(_,i)=>({file:String(i),name:'Sound '+i}));
sbState.total=1000;
paintSounds();assert.equal(created,1000);
for(let i=0;i<100;i++) paintSounds();
assert.equal(created,1000);assert.equal(replaced,1);
sbState.playing='1';paintSounds();assert.equal(created,1001);
sbState.playing='2';paintSounds();assert.equal(created,1003);
sbState.saving.add('3');paintSounds();assert.equal(created,1004);
sbState.sounds=sbState.sounds.slice(0,10);paintSounds();assert.equal(sbRows.size,10);
''')

    def test_sound_finder_matches_music_panel_height_and_position(self):
        self.run_js('soundbank.js', r'''
const panel=$('railPop'),dialog=$('soundDlg');
dialog.style={};dialog.open=true;
panel.getBoundingClientRect=()=>({top:0,left:1000,width:300,height:620});
resizeSoundFinder();assert.equal(dialog.style.height,'620px');assert.equal(dialog.style.top,'0px');assert.equal(dialog.style.width,'300px');
panel.getBoundingClientRect=()=>({top:10,left:800,width:280,height:410});
resizeSoundFinder();assert.equal(dialog.style.height,'410px');assert.equal(dialog.style.top,'10px');assert.equal(dialog.style.left,'800px');
dialog.open=false;dialog.style.height='unchanged';resizeSoundFinder();assert.equal(dialog.style.height,'unchanged');
''')
