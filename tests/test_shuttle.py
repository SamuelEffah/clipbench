"""J, K and L playback on the Short: the speed ladder, switching direction, and stopping."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / 'scripts/clipper_ui/shuttle.js').read_text()


def run(steps, paused=True, done=False, elapsed=10.0, end=30.0):
    """Press the keys in `steps` ("L", "J", "K", "wait:<ms>", "other") and report what happened after each."""
    script = r'''
const frames = [];
let clock = 0;
const performance = {now: () => clock};
const requestAnimationFrame = fn => { frames.push(fn); return frames.length; };
const cancelAnimationFrame = () => { frames.length = 0; };
const toasts = [], seeks = [];
const toast = t => toasts.push(t);
const video = {paused: %(paused)s, seeking: false, pause() { this.paused = true; }, play() { this.paused = false; return Promise.resolve(); }};
const preview = {done: %(done)s, elapsed: %(elapsed)s, hold: false};
const shortEnd = () => %(end)s;
const seekShort = t => { seeks.push(Math.round(t * 100) / 100); preview.elapsed = t; };
const startPreviewAt = () => { preview.done = false; video.paused = false; seeks.push("restart"); };
const nextTop = () => 0;
const document = {addEventListener() {}};
''' % {'paused': json.dumps(paused), 'done': json.dumps(done), 'elapsed': elapsed, 'end': end} + SOURCE + r'''
const log = [];
for (const step of %s) {
  if (step === "L") shuttleKey(1);
  else if (step === "J") shuttleKey(-1);
  else if (step === "K") shuttleStop();
  else if (step === "other") stopShuttle();
  else if (step.startsWith("wait:")) {
    const ms = Number(step.slice(5));
    for (let t = 0; t < ms; t += 20) { clock += 20; const f = frames.splice(0); f.forEach(fn => fn(clock)); }
  }
  log.push({rate: shuttle ? shuttle.dir * shuttle.rate : 0, paused: video.paused, hold: preview.hold, at: Math.round(preview.elapsed * 100) / 100});
}
console.log(JSON.stringify({log, toasts, seeks}));
''' % json.dumps(steps)
    done = subprocess.run(['node', '-e', script], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@unittest.skipUnless(shutil.which('node'), 'Node required')
class Shuttle(unittest.TestCase):
    def test_l_from_a_stop_plays_forward_at_normal_speed(self):
        out = run(['L'])
        self.assertEqual(out['log'][0]['rate'], 0)
        self.assertFalse(out['log'][0]['paused'])
        self.assertFalse(out['log'][0]['hold'])
        self.assertEqual(out['toasts'], ['Play'])

    def test_l_again_while_playing_goes_to_2x_then_4x_then_8x_and_stays(self):
        out = run(['L', 'L', 'L', 'L', 'L'])
        self.assertEqual([s['rate'] for s in out['log']], [0, 2, 4, 8, 8])
        self.assertEqual(out['toasts'][1:], ['Forward 2x', 'Forward 4x', 'Forward 8x', 'Forward 8x'])

    def test_j_goes_backward_and_gets_faster_the_same_way(self):
        out = run(['J', 'J', 'J'])
        self.assertEqual([s['rate'] for s in out['log']], [-1, -2, -4])

    def test_the_playhead_moves_at_the_speed_asked_for(self):
        out = run(['L', 'L', 'wait:1000'], elapsed=5.0)
        self.assertAlmostEqual(out['log'][-1]['at'], 7.0, delta=0.2)
        back = run(['J', 'wait:1000'], elapsed=20.0)
        self.assertAlmostEqual(back['log'][-1]['at'], 19.0, delta=0.2)

    def test_the_opposite_key_changes_direction_at_normal_speed(self):
        out = run(['L', 'L', 'L', 'J'])
        self.assertEqual(out['log'][-1]['rate'], -1)
        out = run(['J', 'J', 'L'])
        self.assertEqual(out['log'][-1]['rate'], 0)
        self.assertFalse(out['log'][-1]['paused'])

    def test_k_stops_and_holds_the_picture(self):
        out = run(['L', 'L', 'K'])
        last = out['log'][-1]
        self.assertEqual(last['rate'], 0)
        self.assertTrue(last['paused'])
        self.assertTrue(last['hold'])

    def test_l_after_k_starts_again_from_normal_speed(self):
        out = run(['L', 'L', 'K', 'L'])
        self.assertEqual(out['log'][-1]['rate'], 0)
        self.assertFalse(out['log'][-1]['paused'])

    def test_running_into_the_start_or_end_stops_the_shuttle(self):
        out = run(['J', 'wait:2000'], elapsed=1.0)
        self.assertEqual(out['log'][-1]['rate'], 0)
        self.assertEqual(out['log'][-1]['at'], 0)
        out = run(['L', 'L', 'wait:3000'], elapsed=28.5, end=30.0)
        self.assertEqual(out['log'][-1]['rate'], 0)
        self.assertEqual(out['log'][-1]['at'], 30.0)

    def test_playing_on_the_finished_short_restarts_it(self):
        out = run(['L'], done=True)
        self.assertIn('restart', out['seeks'])

    def test_going_back_from_the_finished_short_starts_at_the_end(self):
        out = run(['J', 'wait:200'], done=True, elapsed=0.0, end=30.0)
        self.assertGreater(out['log'][-1]['at'], 29.0)

    def test_another_action_hands_control_back(self):
        out = run(['L', 'L', 'other'])
        self.assertEqual(out['log'][-1]['rate'], 0)

    def test_seeks_are_spaced_out_not_one_per_frame(self):
        out = run(['L', 'L', 'wait:1000'], elapsed=5.0)
        self.assertLess(len(out['seeks']), 20)
        self.assertGreater(len(out['seeks']), 5)


if __name__ == '__main__':
    unittest.main()
