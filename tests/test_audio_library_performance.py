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


class AudioLibraryPerformance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root / 'song.mp3'
        self.src.write_bytes(b'audio')
        for name, value in [('AUDIO_DIRS', [self.root]), ('_audio_lengths', {}), ('audio_registry', {})]:
            patch = mock.patch.object(clipper, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_concurrent_library_scans_share_duration_probe(self):
        gate = threading.Barrier(8)
        def duration(path):
            time.sleep(.05)
            return 30
        def request(_):
            gate.wait(timeout=5)
            return clipper.scan_audio()
        with mock.patch.object(clipper, 'probe_duration', side_effect=duration) as probe:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(request, range(8)))
            self.assertTrue(all(result == results[0] for result in results))
            self.assertEqual(results[0][0]['kind'], 'song')
            self.assertEqual(probe.call_count, 1)
            clipper.scan_audio()
            self.assertEqual(probe.call_count, 1)
            self.src.write_bytes(b'changed audio')
            clipper.scan_audio()
            self.assertEqual(probe.call_count, 2)

    def test_expected_probe_failure_stays_cached_until_file_changes(self):
        with mock.patch.object(clipper, 'probe_duration', side_effect=[ValueError('bad audio'), 4]) as probe:
            self.assertEqual(clipper.scan_audio(), [])
            self.assertEqual(clipper.scan_audio(), [])
            self.assertEqual(probe.call_count, 1)
            self.src.write_bytes(b'new audio')
            self.assertEqual(clipper.scan_audio()[0]['kind'], 'sfx')
            self.assertEqual(probe.call_count, 2)

    def test_unexpected_failure_can_be_retried(self):
        with mock.patch.object(clipper, 'probe_duration', side_effect=[RuntimeError('failed'), 5]) as probe:
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                clipper.scan_audio()
            self.assertEqual(clipper.scan_audio()[0]['duration'], 5)
            self.assertEqual(probe.call_count, 2)

    def test_different_audio_files_can_probe_in_parallel(self):
        other = self.root / 'other.mp3'
        other.touch()
        gate = threading.Barrier(2)
        def duration(path):
            gate.wait(timeout=5)
            return 5
        with mock.patch.object(clipper, 'probe_duration', side_effect=duration):
            with ThreadPoolExecutor(max_workers=2) as pool:
                result = list(pool.map(clipper.audio_duration, [self.src, other]))
            self.assertEqual(result, [5, 5])

    def test_duration_cache_discards_old_versions_and_evicts_least_recently_used(self):
        with mock.patch.object(clipper, 'probe_duration', return_value=5) as probe, \
             mock.patch.object(clipper, 'METADATA_CACHE_LIMIT', 8):
            for i in range(100):
                self.src.write_bytes(b'x' * (i + 1))
                self.assertEqual(clipper.audio_duration(self.src), 5)
            self.assertEqual(len(clipper._audio_lengths), 1,
                             'replacing a song must not retain every obsolete version')
            files = [self.root / f'{i}.mp3' for i in range(8)]
            for path in files:
                path.write_bytes(b'audio')
            for path in files[:7]:
                clipper.audio_duration(path)
            before = probe.call_count
            clipper.audio_duration(self.src)  # Promote the active song before eviction.
            clipper.audio_duration(files[7])
            self.assertEqual(len(clipper._audio_lengths), 8)
            clipper.audio_duration(self.src)
            self.assertEqual(probe.call_count, before + 1)
            clipper.audio_duration(files[0])
            self.assertEqual(probe.call_count, before + 2,
                             'the least recently used entry should be probed again')
