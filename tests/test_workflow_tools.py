import json
import shutil
import subprocess
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'


def run_js(source, harness):
    result = subprocess.run(['node', '-e', source + '\n' + harness], capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)


class WorkflowTools(unittest.TestCase):
    def test_transcript_selection_preserves_timing_and_source(self):
        source = (UI / 'livecap.js').read_text().split('function transcriptClip(', 1)[1].split('let transcriptSelection', 1)[0]
        aligned = (UI / 'captions.js').read_text().split('function aligned(', 1)[1].split('// True when', 1)[0]
        run_js('function aligned(' + aligned + '\nfunction transcriptClip(' + source, r'''
const assert = require('assert');
const original = {src:'video', in:10,out:16,wordsIn:10,words:[['one',0,1],['two',1,2],['three',3,4]],caption:'one two three',speed:1.5,lane:'bottom'};
const c=transcriptClip(original,1,2);
assert.equal(c.in,11);assert.equal(c.out,14);assert.equal(c.caption,'two three');assert.equal(c.wordsIn,10);assert.equal(c.src,'video');assert.equal(c.speed,1.5);
assert.equal(original.in,10);assert.equal(original.caption,'one two three');
const trimmed={...original,in:11.5};const t=transcriptClip(trimmed,0,1);assert.equal(t.in,11.5);assert.equal(t.out,14);
assert.equal(transcriptClip(original,2,1),null);assert.equal(transcriptClip(original,0,9),null);
assert.equal(transcriptClip(original,-1,0),null);
''')

    def test_live_moments_are_scoped_bounded_and_do_not_cut(self):
        source = (UI / 'live.js').read_text().split('function momentKey()', 1)[1].split('liveEl("liveMoment").onclick', 1)[0]
        run_js(r'''
const assert=require('assert');const items=new Map();const localStorage={getItem:k=>items.get(k),setItem:(k,v)=>items.set(k,v)};
const state={project:{name:'one'}},live={url:'stream-one',player:{}};let t=42,paints=0;
const domain=()=>({lo:0,hi:100}),liveNow=()=>t,paintBuffer=()=>paints++,toast=()=>{};
''' + 'function momentKey()' + source, r'''
markLiveMoment();markLiveMoment();assert.deepEqual(readMoments(),[42]);t=44;markLiveMoment();assert.deepEqual(readMoments(),[42,44]);
live.url='stream-two';assert.deepEqual(readMoments(),[]);live.url='stream-one';state.project.name='two';assert.deepEqual(readMoments(),[]);
state.project.name='one';assert.deepEqual(readMoments(),[42,44]);
writeMoments(Array.from({length:250},(_,i)=>i));assert.equal(readMoments().length,200);assert.equal(readMoments()[0],50);
items.set(momentKey(),'broken');assert.deepEqual(readMoments(),[]);t=101;markLiveMoment();assert.deepEqual(readMoments(),[]);
''')

    def test_session_restore_is_paused_and_restores_source_and_view(self):
        source = (UI / 'app.js').read_text().split('let sessionReady = false;', 1)[1].split('window.addEventListener("pagehide"', 1)[0]
        run_js(r'''
const assert=require('assert');let sessionReady=true,tlZoom=1,view={s:0,e:60};const stlBody={scrollLeft:12};
const state={project:{name:'one',clips:[{src:'v',in:5,out:20}]},mode:'clip',sel:0,current:{path:'v'}};
const items=new Map(),localStorage={getItem:k=>items.get(k),setItem:(k,v)=>items.set(k,v)};
const tnow=()=>13,preview={on:false,idx:0},render=()=>{},byPath=p=>p==='v'?{path:'v',duration:60}:null;
let opened,redraw=0,sideTab=null;const openVideo=async(v,t)=>{opened=[v.path,t]},redrawView=()=>redraw++,setSideTab=t=>{sideTab=t};
const closePreview=()=>{},usePreviewPlayers=()=>{},canon=()=>state.project,orient=p=>p,resetHistory=()=>{};
const $=()=>({}),layoutCard=()=>{},buildSegs=()=>{},fitPhone=()=>{},renderShortTl=()=>{},syncZoomUi=()=>{};
let started;const startPreviewAt=(i,t)=>{started=[i,t]};
''' + source, r'''
(async()=>{saveEditorSession();const saved=JSON.parse(items.get(sessionKey()));assert.equal(saved.time,13);
view={s:0,e:1};await restoreEditorSession();assert.deepEqual(opened,['v',13]);assert.equal(view.e,60);assert.equal(redraw,1);
saved.mode='short';saved.time=15;saved.zoom=3;saved.scroll=42;items.set(sessionKey(),JSON.stringify(saved));await restoreEditorSession();assert.equal(preview.hold,true);assert.deepEqual(started,[0,15]);assert.equal(tlZoom,3);assert.equal(stlBody.scrollLeft,42);
state.project.name='two';started=null;await restoreEditorSession();assert.equal(started,null);
items.set(sessionKey(),'not json');await restoreEditorSession();assert.equal(sessionReady,true);
})().catch(e=>{console.error(e);process.exitCode=1});
''')


@unittest.skipUnless(shutil.which('node'), 'Node required')
class BlockedAutoplay(unittest.TestCase):
    def test_a_blocked_start_plays_muted_and_unmutes_on_the_first_touch(self):
        source = (UI / 'live.js').read_text()
        source = source[source.index('function playMutedUntilTouched'):source.index('// Loading another link')]
        script = r'''
const assert=require('assert');
const added=[],removed=[],toasts=[];
const document={addEventListener:(t,f)=>added.push([t,f]),removeEventListener:(t,f)=>removed.push([t,f])};
const toast=m=>toasts.push(m);
''' + source + r'''
const log=[];
playMutedUntilTouched(()=>log.push('mute'),()=>log.push('unmute'));
assert.deepEqual(log,['mute']);assert.equal(toasts.length,1);
assert.deepEqual(added.map(a=>a[0]).sort(),['keydown','pointerdown']);
added[0][1]();
assert.deepEqual(log,['mute','unmute']);assert.equal(removed.length,2);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
