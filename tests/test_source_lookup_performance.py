import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class SourceLookupPerformance(unittest.TestCase):
    def test_source_index_is_built_once_per_library_and_preserves_lookup_results(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/app.js').read_text()
        lookup = source.split('// B-roll footage', 1)[1].split('const stripExt', 1)[0]
        # Start at the source helpers rather than their introductory comment.
        lookup = lookup[lookup.index('const sourcesOf'):]
        script = r'''
const assert=require('node:assert/strict');
let reads=0;
const state={library:Array.from({length:2000},(_,i)=>({
 get path(){reads++;return `source${i}`;},name:`Video ${i}`,ready:true
}))};
''' + lookup + r'''
const last=state.library.at(-1);
for(let n=0;n<600;n++) assert.equal(byPath('source1999'),last);
assert.ok(reads<=4000,`${reads} source path reads for repeated playback lookups`);
assert.equal(byPath('missing'),undefined);
last.name='Renamed';last.ready=false;
assert.equal(byPath('source1999').name,'Renamed');
assert.equal(byPath('source1999').ready,false);
// Refreshing a library or switching projects replaces the list.
const first={path:'same',name:'First'},duplicate={path:'same',name:'Second'};
state.library=[first,duplicate,{path:'new',name:'New'}];
assert.equal(byPath('same'),first,'preserve the first matching source');
assert.equal(byPath('new').name,'New');assert.equal(byPath('source1999'),undefined);
state.library=[duplicate];assert.equal(byPath('same'),duplicate);
state.library=[];assert.equal(byPath('same'),undefined);
state.library=[{path:'__proto__'},{path:'constructor'}];
assert.equal(byPath('__proto__'),state.library[0]);
assert.equal(byPath('constructor'),state.library[1]);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
