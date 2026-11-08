"""Exercise browser rendering containment and real viewport observation in isolation."""
import json
import shutil
import subprocess
import tempfile
import time
from urllib.request import urlopen

try:
    from websockets.sync.client import connect
except ImportError:
    connect = None
import unittest
from pathlib import Path

CHROME = shutil.which('chromium') or shutil.which('google-chrome')
if not CHROME:
    mac_chrome = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    CHROME = str(mac_chrome) if mac_chrome.is_file() else None


@unittest.skipUnless(CHROME and connect, 'Headless Chrome and websockets required')
class BrowserOffscreenRenderingTests(unittest.TestCase):
    def test_offscreen_rows_skip_rendering_without_changing_geometry_or_focus(self):
        ui = Path(__file__).resolve().parents[1] / 'scripts/clipper_ui'
        css = (ui / 'style.css').read_text()
        app = (ui / 'app.js').read_text()
        helper = 'function paintWhenVisible(' + app.split('function paintWhenVisible(', 1)[1].split('\nfunction prepareWaveCanvas(', 1)[0]
        rows = ''.join(f'<div class="media" tabindex="0"><div class="thumb"></div><div><b>Source {i}</b><small>10 seconds</small></div><button class="mediadel">Open</button></div>' for i in range(1000))
        clips = ''.join(f'<div class="stl-clip" tabindex="0" style="left:{i*120}px;width:100px"><b class="stl-name">Clip {i}</b></div>' for i in range(1000))
        script = r'''
const check=(v,message)=>{if(!v)throw Error(message);};
const shown=el=>el.checkVisibility({contentVisibilityAuto:true});
const result=document.getElementById('result');
const delay=async()=>{await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);await new Promise(r=>setTimeout(r,120));};
(async()=>{
 await delay();
 const viewport=document.getElementById('viewport'),rows=[...document.querySelectorAll('.media')];
 const first=rows[0],last=rows.at(-1),height=first.getBoundingClientRect().height;
 check(shown(first.querySelector('b')),'visible source title missing');
 check(!shown(last.querySelector('b')),'offscreen source contents still render');
 check(height===48,'source row theme geometry changed: '+height);
 check(last.getBoundingClientRect().height===height,'offscreen placeholder changed source row height');
 viewport.scrollTop=last.offsetTop;await delay();
 check(shown(last.querySelector('b')),'scrolling must reveal source contents');
 check(last.getBoundingClientRect().height===height,'scrolling changed row height');
 first.querySelector('button').focus();await delay();
 check(document.activeElement===first.querySelector('button'),'offscreen keyboard target lost');
 check(shown(first.querySelector('b')),'focusing a source must reveal it');
 document.body.dataset.mode='short';
 const horizontal=document.getElementById('horizontal'),clips=[...document.querySelectorAll('.stl-clip')];
 let paints=0;
 clips.forEach(el=>paintWhenVisible(el,()=>paints++));
 await delay();
 check(paints>0&&paints<20,'painted too many offscreen waveforms: '+paints);
 const far=clips.at(-1),width=far.getBoundingClientRect().width;
 check(!shown(far.querySelector('b')),'offscreen clip contents still render');
 horizontal.scrollLeft=far.offsetLeft;await delay();
 check(shown(far.querySelector('b')),'scrolling must reveal clip contents');
 check(far.getBoundingClientRect().width===width,'clip width changed on reveal');
 check(paints<40,'scrolling eagerly painted all waveforms: '+paints);
 result.textContent=JSON.stringify({ok:true,sourceHeight:height,wavePaints:paints,retainedSources:rows.length,retainedClips:clips.length});
})().catch(e=>{result.textContent=JSON.stringify({ok:false,error:e.message});});
'''
        html = '<!doctype html><meta charset="utf-8"><style>' + css + '''
body{display:block!important;height:600px!important;overflow:hidden!important;padding:0!important}
#viewport{height:220px;width:260px;overflow:auto;position:relative}#library{width:260px}
#horizontal{width:500px;height:80px;overflow:auto}#track{position:relative;width:120000px;height:46px}
</style><body data-mode="clip"><div id="viewport"><div id="library">''' + rows + '</div></div><div id="horizontal"><div id="track">' + clips + '</div></div><pre id="result">pending</pre><script>' + helper + script + '</script>'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture = root / 'fixture.html'
            fixture.write_text(html)
            profile = root / 'profile'
            process = subprocess.Popen([CHROME, '--headless=new', '--disable-gpu', '--no-first-run',
                                        '--no-default-browser-check', '--disable-background-timer-throttling',
                                        '--disable-renderer-backgrounding', f'--user-data-dir={profile}',
                                        '--remote-debugging-port=0', fixture.as_uri()],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 15
                port_file = profile / 'DevToolsActivePort'
                while not port_file.is_file() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(port_file.is_file(), 'browser did not start')
                port = port_file.read_text().splitlines()[0]
                with urlopen(f'http://127.0.0.1:{port}/json/list', timeout=5) as response:
                    pages = json.load(response)
                page = next(p for p in pages if p['type'] == 'page')
                with connect(page['webSocketDebuggerUrl'], open_timeout=5) as socket:
                    content, request = 'pending', 0
                    while content == 'pending' and time.monotonic() < deadline:
                        request += 1
                        socket.send(json.dumps({'id': request, 'method': 'Runtime.evaluate', 'params': {
                            'expression': 'document.getElementById("result")?.textContent || "pending"',
                            'returnByValue': True}}))
                        reply = json.loads(socket.recv(timeout=5))
                        self.assertEqual(reply.get('id'), request)
                        content = reply['result']['result']['value']
                        if content == 'pending':
                            time.sleep(.05)
                self.assertNotEqual(content, 'pending', 'browser test did not finish')
                result = json.loads(content)
                self.assertTrue(result['ok'], result)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
