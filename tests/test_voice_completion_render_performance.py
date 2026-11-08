import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class VoiceCompletionRenderPerformance(unittest.TestCase):
    def test_voice_completion_renders_once_with_final_busy_state_and_preserves_undo(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        voice = (ui / 'voice.js').read_text()
        isolate = 'const voiceWorking' + voice.split('const voiceWorking', 1)[1].split('\nfunction useOriginalSound(', 1)[0]
        app = (ui / 'app.js').read_text()
        def function(name):
            return 'function ' + name + '(' + app.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
const state={project:{name:'project',clips:[]}};
let frames=[],history=[],messages=[],editCount=0,unsaved=false,saveTimer=0,requests=0;
const recordEdit=key=>history.push(key),toast=text=>messages.push(text),save=()=>{},clearTimeout=()=>{},setTimeout=()=>1,$=()=>({});
let respond=async()=>({state:'done'});
const api=async(...args)=>{requests++;return respond(...args);};
const render=()=>frames.push({busy:voiceWorking.size,clips:state.project.clips.map(c=>Boolean(c.voice))});
const makeClip=src=>({src,in:0,out:5});
const reset=clips=>{state.project={name:'project',clips};frames=[];history=[];messages=[];editCount=0;unsaved=false;requests=0;voiceWorking.clear();};
''' + isolate + function('changed') + function('setClipField') + r'''
(async()=>{
reset([makeClip('one')]);await isolateVoice([0]);
assert.equal(frames.length,2,'one initial render and one completed render, without an intermediate busy render');
assert.deepEqual(frames,[{busy:1,clips:[false]},{busy:0,clips:[true]}]);assert.equal(requests,1);assert.equal(editCount,1);assert.deepEqual(history,['']);assert.equal(unsaved,true);assert.equal(voiceWorking.size,0);
reset([makeClip('one'),makeClip('two')]);await isolateVoice([0,1]);assert.equal(frames.length,3);assert.equal(history.length,2);assert.ok(state.project.clips.every(c=>c.voice));assert.equal(frames.at(-1).busy,0);
// Failures still clear Processing and redraw, without recording an edit.
reset([makeClip('bad')]);respond=async()=>{throw Error('failed');};await isolateVoice([0]);assert.equal(frames.length,2);assert.equal(history.length,0);assert.equal(voiceWorking.size,0);assert.deepEqual(messages,['failed']);assert.equal(state.project.clips[0].voice,undefined);
// A result arriving after switching projects must not edit the new project.
reset([makeClip('old')]);let resolve;respond=()=>new Promise(r=>resolve=r);const pending=isolateVoice([0]);
state.project={name:'other',clips:[makeClip('new')]};resolve({state:'done'});await pending;assert.equal(history.length,0);assert.equal(state.project.clips[0].voice,undefined);assert.equal(frames.at(-1).busy,0);
// A moved clip is found by its source range when its job finishes.
reset([makeClip('one'),makeClip('two')]);respond=()=>new Promise(r=>resolve=r);const moved=isolateVoice([0]);state.project.clips.reverse();resolve({state:'done'});await moved;assert.equal(state.project.clips[1].voice,true);assert.equal(state.project.clips[0].voice,undefined);assert.equal(frames.length,2);
// Already completed or busy clips perform no work; ordinary field edits still render immediately.
reset([{...makeClip('done'),voice:true},makeClip('busy')]);voiceWorking.add(voiceKey(state.project.clips[1]));await isolateVoice([0,1]);assert.equal(requests,0);assert.equal(frames.length,0);
setClipField(0,{volume:.5});assert.equal(frames.length,1);assert.equal(state.project.clips[0].volume,.5);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
