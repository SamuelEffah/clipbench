import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class SavedLookupPerformance(unittest.TestCase):
    def test_rendering_compares_only_same_source_and_preserves_trim_tolerance(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        helper = 'function momentFinder(' + source.split('function momentFinder(', 1)[1].split('async function saveFavorites(', 1)[0]
        def function(name):
            return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
let comparisons=0;
const sameMoment=(a,b)=>{comparisons++;return a.src===b.src&&Math.abs(a.in-b.in)<.05&&Math.abs(a.out-b.out)<.05;};
''' + helper + r'''
// Compare against the original predicate at strict tolerance boundaries and random trims.
let seed=27;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
const clips=Array.from({length:500},(_,i)=>({src:`video${i%25}`,in:rand()*20,out:rand()*20}));
const lookup=momentLookup(clips);
for(let i=0;i<1000;i++) {
 const c=i<500?{...clips[i],in:clips[i].in+[0,.049,.05,.051,-.05][i%5]}:{src:`video${i%30}`,in:rand()*20,out:rand()*20};
 assert.equal(lookup(c),clips.some(f=>sameMoment(f,c)));
}
// A new render sees edits without retaining an invalidatable cache.
clips.push({src:'new',in:0,out:1});assert.equal(momentLookup(clips)({src:'new',in:0,out:1}),true);
const element=()=>({children:[],classList:{remove(){},add(){}},appendChild(e){this.children.push(e);},querySelector(){return element();},querySelectorAll(){return [];},scrollIntoView(){}});
const elements=new Map(),$=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);};
const document={createElement:element};
const state={mode:'clip',sel:-1,arrived:-1,project:{clips:[]},favorites:[]};
const byPath=src=>({name:src+'.mp4'}),esc=s=>s,mmss=String,fmt=String,outLen=c=>c.out-c.in;
const cutIds=new Set(),cutKey=c=>c.src,clipName=f=>f.src,volumeOf=f=>f.volume??1;
let favFilter='';const TRAY_MIME='tray';
''' + function('renderTray') + function('renderFavs') + r'''
state.project.clips=Array.from({length:2000},(_,i)=>({src:`v${i}`,in:0,out:5}));
state.favorites=Array.from({length:2000},(_,i)=>({src:`v${i}`,in:i%2?.1:0,out:5}));
comparisons=0;renderTray();assert.equal(comparisons,2000);
const tray=$('tray').children;assert.equal(tray.length,2000);
assert.ok(tray[0].innerHTML.includes('star on'));assert.ok(!tray[1].innerHTML.includes('star on'));
comparisons=0;renderFavs();assert.equal(comparisons,2000);
const saved=$('favList').children;assert.equal(saved.length,2000);
assert.ok(saved[0].innerHTML.includes('In Short'));assert.ok(!saved[1].innerHTML.includes('In Short'));
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
