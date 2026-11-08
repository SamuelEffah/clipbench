import sys
import tempfile
import threading
import time
import tracemalloc
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import voice_isolation as voice


class VoiceIsolationConcurrency(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.folder = self.root / 'voices'
        self.src = str(self.root / 'source.mp4')
        Path(self.src).write_bytes(b'video')
        self.separations = 0
        self.counter_lock = threading.Lock()
        patch = mock.patch.object(voice, 'available', return_value=True)
        patch.start()
        self.addCleanup(patch.stop)

    def encode(self, args, **kwargs):
        if '-m' in args:
            with self.counter_lock:
                self.separations += 1
            time.sleep(.05)
            folder = Path(args[args.index('-o') + 1])
            output = folder / voice.MODEL / 'clip' / 'vocals.wav'
            output.parent.mkdir(parents=True)
            output.write_bytes(b'voice')
        else:
            Path(args[-1]).write_bytes(b'audio')
        return SimpleNamespace(returncode=0, stderr='')

    def test_simultaneous_requests_separate_once_and_reuse_saved_voice(self):
        gate = threading.Barrier(8)
        def request(_):
            gate.wait(timeout=5)
            try:
                return voice.isolate(self.folder, self.src, 0., 2.)
            except Exception as err:
                return err
        with mock.patch.object(voice.subprocess, 'run', side_effect=self.encode) as run:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(request, range(8)))
            self.assertEqual(self.separations, 1)
            target = voice.cached_path(self.folder, self.src, 0., 2.)
            self.assertEqual(results, [target] * 8)
            self.assertEqual(target.read_bytes(), b'voice')
            self.assertEqual(run.call_count, 2)
            self.assertEqual(voice.isolate(self.folder, self.src, 0., 2.), target)
            self.assertEqual(run.call_count, 2)
        self.assertEqual(voice._pending, {})

    def test_different_ranges_and_tracks_can_separate_in_parallel(self):
        gate = threading.Barrier(2)
        def run(args, **kwargs):
            if '-m' in args:
                gate.wait(timeout=5)
            return self.encode(args, **kwargs)
        with mock.patch.object(voice.subprocess, 'run', side_effect=run):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(voice.isolate, self.folder, self.src, 0., 2., 0)
                second = pool.submit(voice.isolate, self.folder, self.src, 1., 3., 1)
                paths = [first.result(timeout=5), second.result(timeout=5)]
        self.assertNotEqual(paths[0], paths[1])
        self.assertTrue(all(path.read_bytes() == b'voice' for path in paths))

    def test_failed_decode_is_retried_without_caching_failure(self):
        with mock.patch.object(voice.subprocess, 'run', side_effect=OSError('failed')):
            with self.assertRaisesRegex(OSError, 'failed'):
                voice.isolate(self.folder, self.src, 0., 2.)
        self.assertEqual(voice._pending, {})
        with mock.patch.object(voice.subprocess, 'run', side_effect=self.encode):
            path = voice.isolate(self.folder, self.src, 0., 2.)
        self.assertEqual(path.read_bytes(), b'voice')

    def test_cached_voice_is_available_without_the_separator_installed(self):
        target = voice.cached_path(self.folder, self.src, 0., 2.)
        target.parent.mkdir()
        target.write_bytes(b'saved')
        with mock.patch.object(voice, 'available', return_value=False), mock.patch.object(voice.subprocess, 'run') as run:
            self.assertEqual(voice.isolate(self.folder, self.src, 0., 2.), target)
            run.assert_not_called()

    def test_saving_large_voice_has_bounded_memory_and_preserves_bytes(self):
        chunk = b'voice' * (1024 * 1024 // 5)
        def encode(args, **kwargs):
            if '-m' in args:
                output = Path(args[args.index('-o') + 1]) / voice.MODEL / 'clip' / 'vocals.wav'
                output.parent.mkdir(parents=True)
                with output.open('wb') as stream:
                    for _ in range(32):
                        stream.write(chunk)
            else:
                Path(args[-1]).write_bytes(b'audio')
            return SimpleNamespace(returncode=0, stderr='')
        with mock.patch.object(voice.subprocess, 'run', side_effect=encode):
            tracemalloc.start()
            try:
                target = voice.isolate(self.folder, self.src, 0., 120.)
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
        self.assertEqual(target.stat().st_size, len(chunk) * 32)
        with target.open('rb') as stream:
            for _ in range(32):
                self.assertEqual(stream.read(len(chunk)), chunk)
            self.assertEqual(stream.read(1), b'')
        self.assertFalse(target.with_suffix('.part').exists())
        self.assertLess(peak, 4 * 1024 * 1024, f'copy allocated {peak} bytes')
