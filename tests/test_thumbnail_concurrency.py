import os
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class ThumbnailConcurrency(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.src = self.root / 'video.mp4'
        self.src.write_bytes(b'video')
        for name, value in [('PROXY_DIR', self.root / 'cache'), ('registry', {'v': self.src})]:
            patch = mock.patch.object(clipper, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(clipper, 'probe', return_value={'duration': 100})
        patch.start()
        self.addCleanup(patch.stop)

    def encode(self, args, **kwargs):
        self.assertEqual(args[args.index('-ss') + 1], '10.00')
        Path(args[-1]).write_bytes(b'jpeg')
        return SimpleNamespace(returncode=0)

    def test_simultaneous_requests_encode_once_and_cache_is_reused(self):
        gate = threading.Barrier(8)
        def encode(*args, **kwargs):
            time.sleep(.05)
            return self.encode(*args, **kwargs)
        def request(_):
            gate.wait(timeout=5)
            return clipper.video_thumb('v')
        with mock.patch.object(clipper.subprocess, 'run', side_effect=encode) as run:
            with ThreadPoolExecutor(max_workers=8) as pool:
                paths = list(pool.map(request, range(8)))
            self.assertEqual(run.call_count, 1)
            self.assertEqual(paths, [clipper.PROXY_DIR / 'v.jpg'] * 8)
            self.assertEqual(paths[0].read_bytes(), b'jpeg')
            self.assertEqual(clipper.video_thumb('v'), paths[0])
            self.assertEqual(run.call_count, 1)

    def test_different_videos_encode_in_parallel(self):
        other = self.root / 'other.mp4'
        other.write_bytes(b'other')
        clipper.registry['other'] = other
        gate = threading.Barrier(2)
        def encode(*args, **kwargs):
            gate.wait(timeout=5)
            return self.encode(*args, **kwargs)
        with mock.patch.object(clipper.subprocess, 'run', side_effect=encode):
            with ThreadPoolExecutor(max_workers=2) as pool:
                paths = list(pool.map(clipper.video_thumb, ['v', 'other']))
        self.assertEqual([p.read_bytes() for p in paths], [b'jpeg'] * 2)

    def test_failed_or_interrupted_encoding_leaves_no_partial_cache_and_retries(self):
        for error in [False, True]:
            def fail(args, **kwargs):
                Path(args[-1]).write_bytes(b'partial')
                if error:
                    raise OSError('interrupted')
                return SimpleNamespace(returncode=1)
            with mock.patch.object(clipper.subprocess, 'run', side_effect=fail):
                if error:
                    with self.assertRaisesRegex(OSError, 'interrupted'):
                        clipper.video_thumb('v')
                else:
                    self.assertIsNone(clipper.video_thumb('v'))
            self.assertEqual(list(clipper.PROXY_DIR.iterdir()), [])
        with mock.patch.object(clipper.subprocess, 'run', side_effect=self.encode):
            self.assertEqual(clipper.video_thumb('v').read_bytes(), b'jpeg')

    def test_replacement_is_atomic_and_changed_sources_rebuild(self):
        cache = clipper.PROXY_DIR / 'v.jpg'
        cache.parent.mkdir()
        cache.write_bytes(b'old')
        os.utime(cache, ns=(0, 0))
        def encode(args, **kwargs):
            Path(args[-1]).write_bytes(b'partial')
            self.assertEqual(cache.read_bytes(), b'old')
            return self.encode(args, **kwargs)
        with mock.patch.object(clipper.subprocess, 'run', side_effect=encode):
            self.assertEqual(clipper.video_thumb('v'), cache)
        self.assertEqual(list(cache.parent.iterdir()), [cache])
        stamp = cache.stat().st_mtime_ns + 1000000000
        self.src.write_bytes(b'changed')
        os.utime(self.src, ns=(stamp, stamp))
        with mock.patch.object(clipper.subprocess, 'run', side_effect=self.encode) as run:
            self.assertEqual(clipper.video_thumb('v'), cache)
            self.assertEqual(run.call_count, 1)

    def test_source_changed_during_encoding_is_not_published(self):
        def encode(*args, **kwargs):
            self.src.write_bytes(b'changed during encoding')
            return self.encode(*args, **kwargs)
        with mock.patch.object(clipper.subprocess, 'run', side_effect=encode):
            self.assertIsNone(clipper.video_thumb('v'))
        self.assertEqual(list(clipper.PROXY_DIR.iterdir()), [])

    def test_missing_source_does_not_launch_ffmpeg(self):
        self.src.unlink()
        with mock.patch.object(clipper.subprocess, 'run') as run:
            self.assertIsNone(clipper.video_thumb('v'))
            self.assertIsNone(clipper.video_thumb('missing'))
            run.assert_not_called()
