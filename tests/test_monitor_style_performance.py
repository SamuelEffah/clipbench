import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class MonitorStylePerformance(unittest.TestCase):
    def test_stable_effect_frames_skip_style_writes_with_css_serialization(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        def function(name):
            return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        helper = ''
        if 'const playbackStyleValues' in source:
            helper = 'const playbackStyleValues' + source.split('const playbackStyleValues', 1)[1].split('let monitorFxOn', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let writes=0,monitorFxOn=false;
// CSSOM can serialize a value differently from the supplied string.
const serialize=value=>String(value).replace(/,\s*/g,', ').replace(/, \./g,', 0.');
const makeStyle=()=>new Proxy({transform:'',filter:'',background:'',boxShadow:''},{set(t,k,v){writes++;t[k]=serialize(v);return true;}});
const videos=[{style:makeStyle()},{style:makeStyle()}];let video=videos[0];
const fx={style:makeStyle()},$=()=>fx,preview={on:false};
let clip={},pose={dx:0,dy:0,zoom:1,gray:false,flash:0,vignette:true,glitch:{split:.02}};
const monitorClip=()=>clip,effectPose=()=>pose;
''' + helper + function('clearMonitorFx') + function('applyMonitorFx') + r'''
applyMonitorFx();assert.equal(monitorFxOn,true);
const initial={...fx.style},transform=video.style.transform;
writes=0;for(let i=0;i<120;i++)applyMonitorFx();assert.equal(writes,0,'unchanged effects must not rewrite serialized styles');
assert.deepEqual({...fx.style},initial);assert.equal(video.style.transform,transform);
// Animated changes update the right properties; outside style edits are repaired.
pose={...pose,dx:.1,gray:true,flash:.25,glitch:{split:.03}};applyMonitorFx();
assert.equal(video.style.transform,serialize('translate(10%, 0%) scale(1)'));assert.equal(video.style.filter,'grayscale(1)');
assert.ok(fx.style.background.includes('0.25'));assert.ok(fx.style.boxShadow.includes('12px'));
video.style.transform='scale(7)';writes=0;applyMonitorFx();assert.equal(writes,1);assert.equal(video.style.transform,serialize('translate(10%, 0%) scale(1)'));
video=videos[1];applyMonitorFx();assert.equal(video.style.filter,'grayscale(1)');
preview.on=true;applyMonitorFx();assert.equal(monitorFxOn,false);
for(const el of videos){assert.equal(el.style.transform,'');assert.equal(el.style.filter,'');}
assert.equal(fx.style.background,'');assert.equal(fx.style.boxShadow,'');
writes=0;for(let i=0;i<120;i++)applyMonitorFx();assert.equal(writes,0);
preview.on=false;applyMonitorFx();assert.equal(video.style.filter,'grayscale(1)');assert.ok(fx.style.background.includes('0.25'));
clip=null;applyMonitorFx();assert.equal(fx.style.background,'');
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
