import json
import os
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class WaveConcurrency(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root / 'video.mp4'
        self.src.write_bytes(b'video')
        for name, value in [('PROXY_DIR', self.root / 'cache'), ('registry', {'v': self.src}),
                            ('audio_registry', {'a': self.src})]:
            patch = mock.patch.object(clipper, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(clipper, 'scan_audio')
        patch.start()
        self.addCleanup(patch.stop)
        self.wave = {'per_sec': 20, 'peaks': [1, 2, 3]}

    def test_simultaneous_requests_decode_once_for_video_and_audio(self):
        for loader, vid, rate in [(clipper.load_wave, 'v', 20), (clipper.load_audio_wave, 'a', 50)]:
            gate = threading.Barrier(8)
            def decode(*args):
                time.sleep(.05)
                return {**self.wave, 'per_sec': rate}
            def request(_):
                gate.wait(timeout=5)
                return loader(vid)
            with mock.patch.object(clipper, 'compute_wave', side_effect=decode) as compute:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    got = list(pool.map(request, range(8)))
                self.assertEqual(got, [{**self.wave, 'per_sec': rate}] * 8)
                self.assertEqual(compute.call_count, 1)
                self.assertEqual(loader(vid), got[0])
                self.assertEqual(compute.call_count, 1)

    def test_failure_is_retried_and_cache_is_valid_json(self):
        with mock.patch.object(clipper, 'compute_wave', side_effect=[RuntimeError('failed'), self.wave]) as compute:
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                clipper.load_wave('v')
            self.assertEqual(clipper.load_wave('v'), self.wave)
            self.assertEqual(compute.call_count, 2)
        cache = clipper.wave_path('v')
        self.assertEqual(json.loads(cache.read_text()), self.wave)
        self.assertEqual(list(cache.parent.iterdir()), [cache])

    def test_different_files_decode_in_parallel(self):
        other = self.root / 'other.mp4'
        other.write_bytes(b'other')
        clipper.registry['other'] = other
        gate = threading.Barrier(2)
        def decode(*args):
            gate.wait(timeout=5)
            return self.wave
        with mock.patch.object(clipper, 'compute_wave', side_effect=decode):
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(list(pool.map(clipper.load_wave, ['v', 'other'])), [self.wave] * 2)

    def test_changed_source_rebuilds_wave(self):
        with mock.patch.object(clipper, 'compute_wave', return_value=self.wave) as compute:
            clipper.load_wave('v')
            cache = clipper.wave_path('v')
            stamp = cache.stat().st_mtime_ns + 1000000000
            self.src.write_bytes(b'changed video')
            os.utime(self.src, ns=(stamp, stamp))
            self.assertEqual(clipper.load_wave('v'), self.wave)
            self.assertEqual(compute.call_count, 2)

    def test_source_changed_during_decode_is_not_cached(self):
        def decode(*args):
            self.src.write_bytes(b'changed while decoding')
            return self.wave
        with mock.patch.object(clipper, 'compute_wave', side_effect=decode):
            self.assertEqual(clipper.load_wave('v'), self.wave)
        self.assertFalse(clipper.wave_path('v').exists())
        self.assertEqual(list(clipper.PROXY_DIR.iterdir()), [])

    def test_interrupted_write_keeps_previous_json_and_cleans_temporary_file(self):
        cache = clipper.wave_path('v')
        cache.parent.mkdir()
        cache.write_text(json.dumps(self.wave))
        os.utime(cache, ns=(0, 0))
        def interrupted(wave, out):
            out.write('{')
            self.assertEqual(json.loads(cache.read_text()), self.wave)
            raise RuntimeError('interrupted')
        with mock.patch.object(clipper, 'compute_wave', return_value=self.wave), \
                mock.patch.object(clipper.json, 'dump', side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                clipper.load_wave('v')
        self.assertEqual(list(cache.parent.iterdir()), [cache])
        with mock.patch.object(clipper, 'compute_wave', return_value=self.wave):
            self.assertEqual(clipper.load_wave('v'), self.wave)
