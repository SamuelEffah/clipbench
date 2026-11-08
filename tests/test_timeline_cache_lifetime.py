import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required')
class TimelineCacheLifetimeTests(unittest.TestCase):
    def test_render_drops_cached_nodes_for_clips_retained_only_in_history(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/short.js').read_text()
        render = 'function renderShortTl() {' + source.split('function renderShortTl() {', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
const historical={id:'removed'},active={id:'active'};
const state={project:{clips:[historical,active]}};
function clipBlock(){}function soundBlock(){}
const syncPicked=()=>{},LANES=['top'],laneCount=()=>1,laneTotals=()=>new Map([['top',1]]),TL_SECONDS=10,tlZoom=1;
let stlBasePps,stlPps;const stlBody={clientWidth:1000,scrollLeft:0,style:{setProperty(){}},classList:{toggle(){}},replaceChildren(){}};
const shortRuler=()=>null,textRow=()=>null,audioLane=()=>null,paintLaneHeads=()=>{},paintPlayhead=()=>{};
function laneRow(lane,list){for(const c of list){clipBlock.cache.set(c,clipBlock.previous?.get(c)||{id:c.id});}return null;}
function soundRow(lane,list){for(const c of list){soundBlock.cache.set(c,soundBlock.previous?.get(c)||{id:c.id});}return null;}
''' + render + r'''
renderShortTl();const clip=clipBlock.cache.get(active),sound=soundBlock.cache.get(active);
state.project={clips:[active]};renderShortTl();
assert.equal(clipBlock.cache.get(active),clip);assert.equal(soundBlock.cache.get(active),sound);
assert.equal(clipBlock.cache.has(historical),false);assert.equal(soundBlock.cache.has(historical),false);
assert.equal(clipBlock.previous,null);assert.equal(soundBlock.previous,null);
state.project={clips:[historical,active]};renderShortTl();assert.ok(clipBlock.cache.has(historical));assert.equal(clipBlock.cache.get(active),clip);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
