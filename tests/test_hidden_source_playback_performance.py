import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class HiddenSourcePlaybackPerformance(unittest.TestCase):
    def test_short_preview_skips_source_caption_scan_and_hidden_controls(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        update = 'function updateTime(' + source.split('function updateTime(', 1)[1].split('\nfunction seekBy(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let reads=0,lookups=0,heads=0,formats=0;
const clips=Array.from({length:2000},()=>({src:'/video',caption:'',in:0,out:5}));
const state={mode:'short',current:{path:'/video',duration:60},project:{clips:new Proxy(clips,{get(t,k,r){if(/^\d+$/.test(String(k)))reads++;return Reflect.get(t,k,r);}})}};
const video={currentTime:2,duration:60,paused:false};
const attrs={href:''},icon={getAttribute:k=>attrs[k],setAttribute(k,v){attrs[k]=v;}};
const ids=new Map(),$=id=>{lookups++;if(!ids.has(id))ids.set(id,{textContent:'',querySelector:()=>icon});return ids.get(id);};
const fmt=t=>{formats++;return String(t);},placePlayhead=()=>heads++,setPlaybackValue=(target,key,value)=>target[key]=value;
''' + update + r'''
for(let i=0;i<120;i++)updateTime();assert.equal(reads,0,'Short playback must not search source captions');assert.equal(lookups,0);assert.equal(heads,0);assert.equal(formats,0);
// Returning to Clip mode refreshes source time, caption, icon, and playhead immediately.
state.mode='clip';clips[1999].caption='Hello';updateTime();
assert.equal($('tcNow').textContent,'2');assert.equal($('tcTot').textContent,'60');assert.equal($('srcSub').textContent,'Hello');assert.equal(attrs.href,'#c-pause');assert.equal(heads,1);
video.currentTime=8;video.paused=true;updateTime();assert.equal($('srcSub').textContent,'');assert.equal(attrs.href,'#c-play');
state.mode='short';reads=lookups=0;updateTime();assert.equal(reads,0);assert.equal(lookups,0);
state.mode='clip';state.current=null;video.duration=NaN;updateTime();assert.equal($('tcTot').textContent,'0');assert.equal($('srcSub').textContent,'');
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
