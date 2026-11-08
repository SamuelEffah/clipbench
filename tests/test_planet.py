"""Planet lifecycle: rotation, fixed lighting, fallback, and bounded rendering."""
import json
from pathlib import Path
import subprocess
import unittest

SOURCE = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/planet.js').read_text()


class PlanetRendering(unittest.TestCase):
    def test_motion_and_failure_lifecycle(self):
        harness = r'''
const vm=require('vm'),assert=require('assert');
function fixture({supported=true,compile=true,motion=true}={}){
 const handlers={},docEvents={},windowEvents={},frames=new Map(),uniforms=[],shaders=[];
 let seq=0,draws=0,deleted=0;
 const gl=new Proxy({getShaderParameter:()=>compile,getProgramParameter:()=>true,getAttribLocation:()=>0,getUniformLocation:(_,name)=>name,uniform1f:(name,value)=>uniforms.push([name,value]),drawArrays:()=>draws++,shaderSource:(_,source)=>shaders.push(source),deleteProgram:()=>deleted++},{get(o,k){if(k in o)return o[k];if(k.startsWith('create'))return ()=>({});return (...args)=>{};}});
 const canvas={hidden:true,width:300,height:150,parentElement:{},getContext:()=>supported?gl:null,getBoundingClientRect:()=>({width:1500}),addEventListener:(e,fn)=>handlers[e]=fn};
 const fallback={hidden:false};const reduced={matches:!motion,addEventListener:(e,fn)=>handlers.motion=fn};
 let image;
 const context={document:{hidden:false,getElementById:id=>id==='planet-canvas'?canvas:fallback,addEventListener:(e,fn)=>docEvents[e]=fn},matchMedia:()=>reduced,devicePixelRatio:3,Image:class{constructor(){image=this;this.complete=true;this.naturalWidth=1440;}},ResizeObserver:class{observe(){}},window:{addEventListener:(e,fn)=>windowEvents[e]=fn},requestAnimationFrame:fn=>{let id=++seq;frames.set(id,fn);return id;},cancelAnimationFrame:id=>frames.delete(id),Float32Array,Math};
 vm.runInNewContext(SOURCE,context);
 return {canvas,fallback,reduced,frames,handlers,docEvents,windowEvents,uniforms,shaders,context,get draws(){return draws;},get deleted(){return deleted;},load(){image.onload();},frame(now){const callbacks=[...frames.values()];frames.clear();callbacks.forEach(fn=>fn(now));}};
}
let f=fixture();f.load();assert(!f.canvas.hidden);assert(f.fallback.hidden);assert.equal(f.canvas.width,768);assert.equal(f.canvas.height,768);
f.frame(1000);f.frame(1050);assert(f.uniforms.filter(([name])=>name==='angle').at(-1)[1]>.03);assert(f.shaders.some(s=>s.includes('atan(local.x,normal.z)')));assert(f.shaders.some(s=>s.includes('normalize(vec3(-.7,.5,1.45))')));
f.context.document.hidden=true;f.docEvents.visibilitychange();assert.equal(f.frames.size,0);const paused=f.draws;
f.frame(2000);assert.equal(f.draws,paused);f.context.document.hidden=false;f.docEvents.visibilitychange();assert.equal(f.frames.size,1);
f.reduced.matches=true;f.handlers.motion();assert.equal(f.frames.size,0);assert(!f.canvas.hidden);
f.handlers.webglcontextlost({preventDefault(){}});assert(f.canvas.hidden);assert(!f.fallback.hidden);assert.equal(f.frames.size,0);
f.handlers.webglcontextrestored();assert(!f.canvas.hidden);assert(f.fallback.hidden);
f=fixture({compile:false});f.load();assert(f.canvas.hidden);assert(!f.fallback.hidden);assert.equal(f.frames.size,0);
f=fixture({supported:false});assert(f.canvas.hidden);assert(!f.fallback.hidden);
f=fixture({motion:false});f.load();assert(!f.canvas.hidden);assert.equal(f.frames.size,0);assert.equal(f.draws,2);
console.log('Planet motion and lifecycle passed');
'''
        result = subprocess.run(['node', '-e', 'const SOURCE=' + json.dumps(SOURCE) + ';\n' + harness], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Planet motion and lifecycle passed', result.stdout)
