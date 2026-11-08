import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class SuggestionSceneReuse(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.src = self.root / 'source.mp4'
        self.src.write_bytes(b'video')
        self.vid = 'scene-reuse'
        patches = [patch.object(clipper, 'PROXY_DIR', self.root / 'proxy'),
                   patch.object(clipper, 'registry', {self.vid: self.src}),
                   patch.object(clipper, 'scene_jobs', {}),
                   patch.object(clipper, 'suggest_jobs', {self.vid: {'state': 'working'}}),
                   patch.object(clipper.embedded_subs, 'all_cues', return_value=[(0, 2, 'Speech')]),
                   patch.object(clipper, 'load_wave', return_value={}),
                   patch.object(clipper, 'probe', return_value={'duration': 10}),
                   patch.object(clipper.suggest, 'ollama_models', return_value=[]),
                   patch.object(clipper.suggest, 'suggest', return_value=[])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_suggestion_reuses_the_scene_scan_it_just_started(self):
        def thread(*, target, args, **kwargs):
            return Mock(start=lambda: target(*args))
        with patch.object(clipper.threading, 'Thread', side_effect=thread), \
             patch.object(clipper.video_scan, 'scan', return_value=([1., 2.], None)) as scan, \
             patch.object(clipper, 'detect_scenes', side_effect=AssertionError('second decode')):
            clipper.run_suggest(self.vid)
        self.assertEqual(scan.call_count, 1, 'suggestions must not run a second whole-video scene decode')
        self.assertEqual(clipper.suggest.suggest.call_args.args[2], [1., 2.])
        self.assertEqual(clipper.suggest_jobs[self.vid]['state'], 'ready')

    def test_suggestion_waits_for_an_inflight_scan(self):
        started, release = threading.Event(), threading.Event()
        def detect(src, threshold, min_gap):
            started.set()
            self.assertTrue(release.wait(5))
            return [3., 4.], None
        with patch.object(clipper.video_scan, 'scan', side_effect=detect) as scan:
            with ThreadPoolExecutor(max_workers=1) as pool:
                work = pool.submit(clipper.run_suggest, self.vid)
                try:
                    self.assertTrue(started.wait(5))
                finally:
                    release.set()
                work.result(timeout=5)
        self.assertEqual(scan.call_count, 1)
        self.assertEqual(clipper.suggest.suggest.call_args.args[2], [3., 4.])

    def test_failed_worker_notifies_waiters_and_existing_fallback_retries(self):
        def thread(*, target, args, **kwargs):
            return Mock(start=lambda: target(*args))
        with patch.object(clipper.threading, 'Thread', side_effect=thread), \
             patch.object(clipper.video_scan, 'scan', side_effect=RuntimeError('worker failed')) as worker, \
             patch.object(clipper, 'detect_scenes', return_value=[5.]) as scan:
            clipper.run_suggest(self.vid)
        self.assertEqual(worker.call_count, 1)
        self.assertEqual(scan.call_count, 1)
        self.assertEqual(clipper.suggest.suggest.call_args.args[2], [5.])
        self.assertEqual(clipper.suggest_jobs[self.vid]['state'], 'ready')
