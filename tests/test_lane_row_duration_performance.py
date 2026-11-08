import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), "node isn't installed")
class LaneRowDurationPerformance(unittest.TestCase):
    def test_rendered_clip_and_sound_positions_reuse_transition_durations(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        def function(file, name):
            source = (ui / file).read_text()
            return 'function ' + name + '(' + source.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0] + '\n}'
        script = r'''
const assert=require('node:assert/strict');
let durations=0;
const outLen=c=>{durations++;return c.len;},laneOf=c=>c.lane||'top',transitionOf=c=>c.transition||'none',tlenOf=c=>c.tlen||.3;
const element=()=>({children:[],style:{},dataset:{},classList:{toggle(){}},append(...els){this.children.push(...els);},appendChild(el){this.children.push(el);},querySelector(){return this.children.find(c=>c.type==='clip')||null;}});
const document={createElement:element};
const clipBlock=(c,index,left,width,dim)=>Object.assign(element(),{type:'clip',index,left,width,dim});
const seamButton=(c,index,x,first)=>({type:'seam',index,x,first});
const byPath=src=>src==='missing'?null:{path:src};
const soundBlock=(c,index,at,pps,v)=>({type:'sound',index,at,pps,src:v.path});
const laneMuted=()=>false,laneDimmedBySolo=()=>false,laneLocked=()=>false,soundCollapsed=()=>false;
''' + function('app.js', 'seamOverlap') + function('app.js', 'introLength') + function('short.js', 'laneRow') + function('short.js', 'soundRow') + r'''
const clips=Array.from({length:2000},()=>({src:'video',len:5,transition:'fade'}));
laneRow('top',clips,10,10000);assert.ok(durations<=2001,`${durations} duration calculations for a clip row`);
durations=0;soundRow('top',clips,10);assert.equal(durations,2000,'sound rows should calculate each duration once');
function previous(lane,list,pps,topLen) {
 let at=0,prev=null;const blocks=[],seams=[],sounds=[];
 list.forEach((c,index)=>{if(laneOf(c)!==lane)return;const len=outLen(c),overlap=seamOverlap(prev,c);at-=overlap;
 blocks.push({type:'clip',index,left:at*pps,width:len*pps,dim:lane!=='top'&&at>=topLen-.01,dataset:{t0:at,t1:at+len,lane}});
 seams.push({type:'seam',index,x:prev?(at+overlap/2)*pps:Math.max(14,introLength(c)/2*pps),first:!prev});
 const v=byPath(c.src);if(v)sounds.push({type:'sound',index,at,pps,src:v.path});at+=len;prev=c;});
 return {clips:[...blocks,...seams],sounds};
}
const fields=({type,index,left,width,dim,dataset,x,first})=>type==='clip'?{type,index,left,width,dim,dataset}:{type,index,x,first};
let seed=51;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let run=0;run<500;run++) {
 const list=Array.from({length:Math.floor(rand()*40)},()=>({src:rand()<.2?'missing':'video',lane:rand()<.5?'top':'lower',len:rand()<.2?0:rand()*10,transition:rand()<.4?'none':'fade',tlen:rand()*2}));
 const pps=rand()*50,topLen=rand()*20;
 for(const lane of ['top','lower','empty']) {
  const expected=previous(lane,list,pps,topLen),row=laneRow(lane,list,pps,topLen),sound=soundRow(lane,list,pps);
  assert.deepEqual(row.children[0].children.map(fields),expected.clips);
  assert.deepEqual(sound.children[0].children,expected.sounds);assert.equal(sound.hidden,expected.sounds.length===0);
 }
}
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
