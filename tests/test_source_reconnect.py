import shutil
import subprocess
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'


@unittest.skipUnless(shutil.which('node'), 'Node required')
class SourceReconnect(unittest.TestCase):
    def test_removing_an_unavailable_source_is_undoable_without_changing_clips(self):
        app = (UI / 'app.js').read_text()
        helper = 'function removeMissingSource(' + app.split('function removeMissingSource(', 1)[1].split('const sourceDisplayName', 1)[0]
        script = r'''
const assert = require('node:assert/strict');
const original = {clips:[{src:'missing',in:1,out:4,caption:'Keep me'}],other:[]};
const state = {project:original,library:[{path:'ready'}]};
let changes=0;const changed=()=>changes++,toast=()=>{};
''' + helper + r'''
removeMissingSource('missing');
assert.deepEqual(state.project.hiddenSources,['missing']);
assert.equal(state.project.clips,original.clips);assert.equal(state.project.other,original.other);
assert.equal(original.hiddenSources,undefined,'undo snapshot is untouched');
assert.deepEqual(JSON.parse(JSON.stringify(state.project)).hiddenSources,['missing']);
removeMissingSource('missing');assert.equal(changes,1,'repeated removal is a no-op');
removeMissingSource('ready');assert.equal(changes,1,'available sources use their existing removal flow');
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_sources_are_grouped_and_reconnect_preserves_clip_edits(self):
        app = (UI / 'app.js').read_text()
        summary = 'function sourceRowsSummary(' + app.split('function sourceRowsSummary(', 1)[1].split('function removeMissingSource', 1)[0]
        drop = (UI / 'dropzone.js').read_text()
        reconnect = 'function reconnectedClips(' + drop.split('function reconnectedClips(', 1)[1].split('$("sourceLocatePick")', 1)[0]
        script = r'''
const assert = require('node:assert/strict');
const a={src:'/missing/talk.mp4',in:3,out:10,caption:'Hello',speed:1.25,volume:.7,thumb:'/old.jpg'};
const b={src:'/ready.mp4',in:0,out:2};
const c={src:'/missing/talk.mp4',in:20,out:30};
const project={clips:[a,b],other:[c]};
''' + summary + reconnect + r'''
const got=sourceRowsSummary(project,[{path:'/ready.mp4'}]);
assert.equal(got.counts.get('/missing/talk.mp4'),2);
assert.deepEqual(got.missing,[{path:'/missing/talk.mp4',name:'talk.mp4',thumb:'/old.jpg',count:2,end:30}]);
const next=reconnectedClips(project.clips,'/missing/talk.mp4','/new.mp4');
assert.deepEqual(next[0],{...a,src:'/new.mp4'}); assert.equal(next[1],b);
assert.equal(a.src,'/missing/talk.mp4','old project remains available to undo');
assert.equal(reconnectedClips(project.other,a.src,'/new.mp4')[0].out,30);
assert.deepEqual(sourceRowsSummary({clips:[]},[]).missing,[]);
assert.equal(sourceRowsSummary({...project,hiddenSources:[a.src]},[{path:'/ready.mp4'}]).missing.length,0);
assert.equal(project.clips.length,2,'hiding a missing source keeps saved clips');
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
