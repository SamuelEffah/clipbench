import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class ShortBadgePerformance(unittest.TestCase):
    def test_badge_checks_only_needed_rows_and_avoids_unchanged_writes(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        source = (ui / 'shorts.js').read_text()
        badge = 'function paintShortsBadge(' + source.split('function paintShortsBadge(', 1)[1].split('\nasync function openShortsDialog(', 1)[0]
        app = (ui / 'app.js').read_text()
        setter = 'function setPlaybackValue(' + app.split('function setPlaybackValue(', 1)[1].split('\nfunction placePlayhead(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
let reads=0,writes=0,renderJob=null,pulse=false;
const state={project:{name:'here'}},shorts={unseen:new Set(),failed:null,rows:[]};
const mineOf=rows=>rows.filter(r=>r.name===state.project.name);
let text='',hidden=true;
const badge={classList:{toggle(k,v){pulse=v;}}};
Object.defineProperties(badge,{textContent:{get:()=>text,set(v){writes++;text=String(v);}},hidden:{get:()=>hidden,set(v){writes++;hidden=v;}}});
const $=()=>badge;
''' + setter + badge + r'''
shorts.rows=Array.from({length:2000},()=>({get name(){reads++;return 'here';},upload:{state:'uploading'}}));
paintShortsBadge();assert.equal(reads,1,'stop at the first relevant upload');assert.equal(text,'1');assert.equal(hidden,false);
writes=0;for(let i=0;i<120;i++)paintShortsBadge();assert.equal(writes,0);
reads=0;shorts.unseen.add('here');paintShortsBadge();assert.equal(reads,0);
shorts.unseen.clear();shorts.failed={name:'here'};paintShortsBadge();assert.equal(reads,0);
shorts.failed=null;renderJob={name:'here'};paintShortsBadge();assert.equal(reads,0);assert.equal(text,'');assert.equal(hidden,false);assert.equal(pulse,true);
let seed=17;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let run=0;run<500;run++) {
 shorts.rows=Array.from({length:30},()=>({name:rand()<.2?'here':'other',upload:{state:['done','error','uploading','none'][Math.floor(rand()*4)]}}));
 shorts.unseen=new Set(rand()<.2?['here']:['other']);shorts.failed=rand()<.2?{name:'here'}:null;renderJob=rand()<.3?{name:rand()<.5?'here':'other'}:null;
 const attention=new Set([...shorts.unseen,...mineOf(shorts.rows).filter(r=>r.upload.state==='uploading'||r.upload.state==='error').map(r=>r.name)]);
 if(shorts.failed)attention.add(shorts.failed.name);
 const busy=attention.has('here'),rendering=Boolean(renderJob&&renderJob.name==='here');
 paintShortsBadge();assert.equal(text,rendering?'':busy?'1':'0');assert.equal(hidden,!rendering&&!busy);assert.equal(pulse,rendering);
}
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
