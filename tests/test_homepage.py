"""Homepage routes and account flow, without user media or real sign-in."""
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock
from scripts import clipper

ROOT = Path(__file__).resolve().parents[1]


class HomeRoutes(unittest.TestCase):
    def test_home_editor_and_local_assets_are_separate_routes(self):
        for path, filename, content_type in (
            ('/', 'home.html', 'text/html; charset=utf-8'),
            ('/editor', 'index.html', 'text/html; charset=utf-8'),
            ('/home.css', 'home.css', 'text/css'),
            ('/home.js', 'home.js', 'text/javascript'),
            ('/planet.js', 'planet.js', 'text/javascript'),
            ('/assets/mars-texture.jpg', 'assets/mars-texture.jpg', 'image/jpeg'),
            ('/assets/mars.jpg', 'assets/mars.jpg', 'image/jpeg'),
        ):
            handler = mock.Mock(path=path)
            handler.host_ok.return_value = True
            clipper.Handler.do_GET(handler)
            handler.serve_file.assert_called_once_with(clipper.UI_DIR / filename, content_type)
            self.assertTrue((clipper.UI_DIR / filename).is_file())

    def test_home_does_not_load_editor_or_external_assets(self):
        html = (clipper.UI_DIR / 'home.html').read_text()
        self.assertNotIn('/app.js', html)
        self.assertIn('src="/assets/mars.jpg"', html)
        self.assertIn('href="/editor"', html)
        self.assertNotIn('planetRotate', (clipper.UI_DIR / 'home.css').read_text())

    def test_account_flow(self):
        source = (clipper.UI_DIR / 'home.js').read_text()
        harness = r'''
const vm=require('vm'),assert=require('assert');
function fixture(initial){
 const elements=new Map(),timers=new Map(),visibility={},windowEvents={};
 let nextTimer=0,assigned='',now=0,calls=[],responses=[initial];
 const el=id=>{if(!elements.has(id))elements.set(id,{textContent:'',hidden:false,disabled:false,listeners:{},addEventListener(e,fn){this.listeners[e]=fn;},showModal(){this.open=true;},close(){this.open=false;}});return elements.get(id);};
 const popup={closed:false,location:{},close(){this.closed=true;}};
 const context={document:{hidden:false,getElementById:el,addEventListener(e,fn){visibility[e]=fn;}},window:{open:()=>popup,addEventListener(e,fn){windowEvents[e]=fn;}},location:{assign:v=>assigned=v},URL,Date:{now:()=>now},setTimeout(fn){const id=++nextTimer;timers.set(id,fn);return id;},clearTimeout(id){timers.delete(id);},fetch:async(path,options)=>{calls.push([path,options.method]);const data=responses.shift();if(data instanceof Error)throw data;if(!data)throw Error('unexpected fetch '+path);return {ok:!data.error,json:async()=>data};}};
 vm.runInNewContext(SOURCE,context);
 return {el,popup,calls,responses,timers,context,visibility,windowEvents,get assigned(){return assigned;},advance(){now=181000;},async click(id){await el(id).listeners.click();},async flush(){for(let i=0;i<12;i++)await Promise.resolve();},async poll(){const entries=[...timers];timers.clear();for(const [,fn]of entries)await fn();await this.flush();}};
}
(async()=>{
 let f=fixture({configured:false,connected:false,message:'Missing client'});await f.flush();await f.click('home-action');assert(f.el('home-setup').open);assert(!f.el('home-skip').hidden);assert.equal(f.calls.length,1);
 f.responses.push({configured:true,connected:false});await f.click('home-recheck');assert(!f.el('home-setup').open);
 f.responses.push({url:'https://accounts.google.com/o/oauth2/auth?state=fixture'});await f.click('home-action');assert(f.popup.location.href.startsWith('https://accounts.google.com/'));assert(f.el('home-action').disabled);
 f.context.document.hidden=true;f.visibility.visibilitychange();assert.equal(f.timers.size,0);
 f.responses.push({configured:true,connected:true});f.context.document.hidden=false;f.visibility.visibilitychange();await f.flush();assert.equal(f.el('home-action-text').textContent,'Open editor');assert(f.el('home-signin').hidden);assert.equal(f.timers.size,0);await f.click('home-action');assert.equal(f.assigned,'/editor');
 f.responses.push({ok:true},{configured:true,connected:false});await f.click('home-disconnect');assert.equal(f.el('home-action-text').textContent,'Connect YouTube');assert(!f.el('home-skip').hidden);
 f=fixture({configured:true,connected:false});await f.flush();f.responses.push({error:'Sign-in failed'});await f.click('home-action');assert(f.popup.closed);assert(!f.el('home-action').disabled);assert.equal(f.el('home-status').textContent,'Sign-in failed');
 f=fixture({configured:true,connected:false});await f.flush();f.responses.push({url:'https://accounts.google.com/signin'});f.context.window.open=()=>null;await f.click('home-action');assert(!f.el('home-signin').hidden);assert.equal(f.el('home-signin').href,'https://accounts.google.com/signin');await f.click('home-cancel');assert.equal(f.timers.size,0);assert(!f.el('home-action').disabled);
 f=fixture({configured:true,connected:false});await f.flush();f.responses.push({url:'https://accounts.google.com/signin'});await f.click('home-action');f.advance();await f.poll();assert(f.el('home-status').textContent.includes('timed out'));assert.equal(f.timers.size,0);
 f=fixture(Error('Offline'));await f.flush();assert.equal(f.el('home-status').textContent,'Offline');assert(!f.el('home-action').disabled);assert(!f.el('home-skip').hidden);
 console.log('Homepage account states passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', 'const SOURCE=' + json.dumps(source) + ';\n' + harness], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Homepage account states passed', result.stdout)
