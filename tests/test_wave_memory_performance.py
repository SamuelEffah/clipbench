import json
import sys
import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class WaveMemoryTests(unittest.TestCase):
    def test_repeated_requests_parse_once_and_file_changes_invalidate_memory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            src, cache = root / 'source', root / 'wave.json'
            src.write_bytes(b'source')
            wave = {'per_sec': 20, 'peaks': list(range(100))}
            cache.write_text(json.dumps(wave))
            with mock.patch.object(Path, 'read_text', autospec=True, side_effect=Path.read_text) as read:
                for _ in range(100):
                    self.assertEqual(clipper._cached_wave(src, cache, 20), wave)
                self.assertEqual(sum(call.args[0] == cache for call in read.call_args_list), 1, 'repeated requests must reuse parsed waveform data')
                changed = {'per_sec': 20, 'peaks': [42]}
                cache.write_text(json.dumps(changed))
                self.assertEqual(clipper._cached_wave(src, cache, 20), changed)
                self.assertEqual(sum(call.args[0] == cache for call in read.call_args_list), 2)
            src.write_bytes(b'changed-source')
            rebuilt = {'per_sec': 20, 'peaks': [2]}
            with mock.patch.object(clipper, 'compute_wave', return_value=rebuilt) as compute:
                self.assertEqual(clipper._cached_wave(src, cache, 20), rebuilt)
                compute.assert_called_once()

    def test_memory_is_bounded_by_entries_and_peak_count(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            src = root / 'source'
            src.write_bytes(b'source')
            with mock.patch.object(clipper, '_wave_memory', OrderedDict()), \
                 mock.patch.object(clipper, 'WAVE_MEMORY_PEAKS', 10):
                for i in range(20):
                    cache = root / f'{i}.json'
                    cache.write_text(json.dumps({'peaks': [1] * 6, 'per_sec': 20}))
                    clipper._cached_wave(src, cache, 20)
                    self.assertLessEqual(sum(len(w['peaks']) for w in clipper._wave_memory.values()), 10)
                self.assertEqual(len(clipper._wave_memory), 1)
                cache = root / 'large.json'
                cache.write_text(json.dumps({'peaks': [1] * 20, 'per_sec': 20}))
                clipper._cached_wave(src, cache, 20)
                self.assertEqual(len(clipper._wave_memory), 1, 'oversized waveforms must not evict useful small entries')

    def test_entry_count_is_bounded_and_recent_entries_are_retained(self):
        with mock.patch.object(clipper, '_wave_memory', OrderedDict()):
            for i in range(8):
                clipper._remember_wave(i, {'peaks': [i]})
            clipper._remember_wave(0, {'peaks': [0]})
            clipper._remember_wave(8, {'peaks': [8]})
            self.assertEqual(len(clipper._wave_memory), 8)
            self.assertIn(0, clipper._wave_memory)
            self.assertNotIn(1, clipper._wave_memory)
