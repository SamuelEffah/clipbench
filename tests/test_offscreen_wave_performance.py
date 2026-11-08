import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class OffscreenWaveTests(unittest.TestCase):
    def test_only_visible_waveforms_paint_and_detached_jobs_are_released(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        app, short, audio = [(ui / name).read_text() for name in ('app.js', 'short.js', 'audio.js')]
        helper = ('function paintWhenVisible(' + app.split('function paintWhenVisible(', 1)[1].split('\nfunction prepareWaveCanvas(', 1)[0]) if 'function paintWhenVisible(' in app else ''
        sound = 'function soundBlock(' + short.split('function soundBlock(', 1)[1].split('// The top-lane', 1)[0]
        audio_block = 'function audioBlock(' + audio.split('function audioBlock(', 1)[1].split('// The level', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let waves=0,levels=0,frames=[],observer;
const element=()=>({style:{},dataset:{},isConnected:true,clientWidth:100,clientHeight:44,classList:{toggle(){},add(){}},append(){},setAttribute(){},addEventListener(){}});
const document={createElement:element,createElementNS:element},window={devicePixelRatio:1};
globalThis.IntersectionObserver=class {
 constructor(callback){this.callback=callback;this.nodes=new Set();observer=this;}
 observe(el){this.nodes.add(el);}unobserve(el){this.nodes.delete(el);}
};
const requestAnimationFrame=fn=>frames.push(fn),flush=()=>{const now=frames;frames=[];now.forEach(fn=>fn());};
const state={sel:-1,project:{clips:[]}},picked=new Set(),voiceWorking=new Set(),clipPeaks=new Map();
const voiceKey=c=>c.in,laneCount=()=>1,outLen=c=>c.out-c.in,volumeOf=()=>1,SND_NS='svg',MAX_VOLUME=2;
const drawClipWave=()=>waves++,drawSoundWave=()=>waves++,addLevelEditor=()=>()=>levels++;
const ROW_H=40,secs=String,esc=String;
''' + helper + sound + audio_block + r'''
const clips=Array.from({length:1000},(_,i)=>({in:i,out:i+1})),v={id:'v'};
const nodes=clips.map((c,i)=>soundBlock(c,i,i,100,v));
const audioNodes=Array.from({length:1000},(_,i)=>audioBlock({id:i,kind:'sfx',dur:1,start:i,label:'sound'},0,100));
flush();
assert.equal(waves,0,'offscreen blocks must not start 2000 waveform paints');
assert.equal(observer.nodes.size,2000);
observer.callback([...nodes.slice(0,10),...audioNodes.slice(0,5)].map(target=>({target,isIntersecting:true})));
assert.equal(waves,15);
clips.forEach((c,i)=>soundBlock(c,i,i,100,v));flush();assert.equal(waves,15,'reused visible blocks need no repeat waveform paint');
const removed=nodes.slice(10,510);removed.forEach(node=>node.isConnected=false);
paintWhenVisible.prune();assert.equal(observer.nodes.size,1485);
// A cached offscreen node can be reattached and observed again later.
nodes[10].isConnected=true;soundBlock(clips[10],10,10,100,v);flush();
assert.ok(observer.nodes.has(nodes[10]));observer.callback([{target:nodes[10],isIntersecting:true}]);assert.equal(waves,16);
// Older browsers preserve eager rendering.
globalThis.IntersectionObserver=undefined;
soundBlock({in:5000,out:5001},5000,5000,100,v);flush();assert.equal(waves,17);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_async_paint_removed_during_loading_can_retry_on_reattachment(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        helper = 'function paintWhenVisible(' + source.split('function paintWhenVisible(', 1)[1].split('\nfunction prepareWaveCanvas(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let observer,resolve,painted=0;
globalThis.IntersectionObserver=class {
 constructor(callback){observer=this;this.callback=callback;this.nodes=new Set();}
 observe(el){this.nodes.add(el);}unobserve(el){this.nodes.delete(el);}
};
const target={isConnected:true};
''' + helper + r'''
(async()=>{
 const draw=async()=>{await new Promise(r=>resolve=r);if(target.isConnected)painted++;};
 paintWhenVisible(target,draw);observer.callback([{target,isIntersecting:true}]);
 target.isConnected=false;resolve();await Promise.resolve();await Promise.resolve();
 assert.equal(painted,0);
 target.isConnected=true;paintWhenVisible(target,draw);
 assert.ok(observer.nodes.has(target),'restored block must retry an interrupted paint');
 observer.callback([{target,isIntersecting:true}]);resolve();await Promise.resolve();await Promise.resolve();
 assert.equal(painted,1);
 paintWhenVisible(target,draw);assert.ok(!observer.nodes.has(target),'completed paint is reused');
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
