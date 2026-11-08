import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class CutWarmPriorityTests(unittest.TestCase):
    def test_background_warming_does_not_enqueue_all_saved_clips(self):
        ranges = [('source', i, i + 1) for i in range(100)]
        checked, release = threading.Event(), threading.Event()
        started = []
        def start(src, a, b):
            started.append(a)
            return {'id': str(a), 'state': 'working'}
        def status(cid):
            checked.set()
            return {'state': 'ready' if release.is_set() else 'working'}
        with mock.patch.object(clipper, 'scan_library'), \
             mock.patch.object(clipper, 'all_clip_ranges', return_value=ranges), \
             mock.patch.object(clipper, 'indexed_cut', return_value=None), \
             mock.patch.object(clipper, 'cut_id', side_effect=lambda src, a, b: str(a)), \
             mock.patch.object(clipper, 'start_cut', side_effect=start), \
             mock.patch.object(clipper, 'cut_status', side_effect=status), \
             mock.patch.object(clipper, 'warm_speech'):
            worker = threading.Thread(target=clipper.warm_cuts)
            worker.start()
            try:
                self.assertTrue(checked.wait(1), 'warm-up must wait for each background conversion')
                self.assertEqual(started, [0], 'only one background clip may be outstanding')
                self.assertEqual(clipper.warm_progress()['total'], 100)
                # Repeated warm-up requests must not create a second batch.
                clipper.warm_cuts()
                self.assertEqual(started, [0])
            finally:
                release.set()
                if hasattr(clipper, 'cut_finished'):
                    with clipper.cut_finished:
                        clipper.cut_finished.notify_all()
                worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(started, list(range(100)))
            self.assertEqual(clipper.warm_progress(), {'total': 100, 'done': 100})
