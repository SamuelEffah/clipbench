import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import transcript_index as ti


class TranscriptCachePerformance(unittest.TestCase):
    def setUp(self):
        ti.clear_cache()
        self.addCleanup(ti.clear_cache)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root / 'video.mp4'
        self.src.write_bytes(b'video')
        self.data = self.root / 'data'
        self.cues = [(1.0, 2.0, 'Hello')]
        ti.save(self.data, self.src, self.cues)

    def test_repeated_loads_parse_once_and_return_independent_lists(self):
        with mock.patch.object(ti.json, 'loads', wraps=json.loads) as parse:
            for _ in range(20):
                loaded = ti.load(self.data, self.src)
                self.assertEqual(loaded, self.cues)
                loaded.clear()
            self.assertEqual(parse.call_count, 1)

    def test_atomic_replacement_with_same_size_and_mtime_is_reloaded(self):
        self.assertEqual(ti.load(self.data, self.src), self.cues)
        target = ti.path_for(self.data, self.src)
        stat = target.stat()
        replacement = target.with_suffix('.new')
        replacement.write_text(target.read_text().replace('Hello', 'Other'))
        os.utime(replacement, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        replacement.replace(target)
        self.assertEqual(ti.load(self.data, self.src), [(1.0, 2.0, 'Other')])

    def test_edits_deletion_and_repair_are_observed(self):
        ti.load(self.data, self.src)
        target = ti.path_for(self.data, self.src)
        target.write_text('{broken')
        self.assertIsNone(ti.load(self.data, self.src))
        ti.save(self.data, self.src, [])
        self.assertEqual(ti.load(self.data, self.src), [])
        target.unlink()
        self.assertIsNone(ti.load(self.data, self.src))
        ti.save(self.data, self.src, self.cues)
        self.assertEqual(ti.load(self.data, self.src), self.cues)

    def test_cached_transcript_still_checks_source_and_data_directory(self):
        ti.load(self.data, self.src)
        other = self.root / 'other'
        ti.save(other, self.src, [(2.0, 3.0, 'Different')])
        self.assertEqual(ti.load(other, self.src), [(2.0, 3.0, 'Different')])
        self.assertEqual(ti.load(self.data, self.src), self.cues)
        self.src.write_bytes(b'a changed source')
        self.assertIsNone(ti.load(self.data, self.src))
        self.src.unlink()
        self.assertIsNone(ti.load(self.data, self.src))

    def test_cache_evicts_old_transcripts(self):
        ti.clear_cache()
        self.addCleanup(ti.clear_cache)
        with mock.patch.object(ti, 'CACHE_ENTRY_LIMIT', 8), mock.patch.object(ti.json, 'loads', wraps=json.loads) as parse:
            for n in range(9):
                folder = self.root / f'library{n}'
                ti.save(folder, self.src, self.cues)
                self.assertEqual(ti.load(folder, self.src), self.cues)
            self.assertEqual(len(ti._line_cache), 8)
            self.assertEqual(ti.load(self.root / 'library0', self.src), self.cues)
            self.assertEqual(parse.call_count, 10)

    def test_two_library_scans_reuse_more_than_eight_transcripts(self):
        sources = [self.root / f'{n}.mp4' for n in range(12)]
        for src in sources:
            src.write_bytes(b'video')
            ti.save(self.data, src, self.cues * 2000)
        with mock.patch.object(ti.json, 'loads', wraps=json.loads) as parse:
            for _ in range(2):
                for src in sources:
                    self.assertEqual(len(ti.load(self.data, src)), 2000)
            self.assertEqual(parse.call_count, 12,
                             'the second dialogue scan should reuse its transcript working set')

    def test_byte_budget_and_oversized_entries_keep_memory_bounded(self):
        with mock.patch.object(ti, 'CACHE_BYTE_LIMIT', 2000):
            for n in range(20):
                folder = self.root / f'budget{n}'
                ti.save(folder, self.src, self.cues)
                ti.load(folder, self.src)
                self.assertLessEqual(ti._line_cache_bytes, 2000)
            self.assertLess(len(ti._line_cache), 20)
            ti.save(self.data, self.src, self.cues * 100)
            size = len(ti._line_cache)
            self.assertEqual(len(ti.load(self.data, self.src)), 100)
            self.assertEqual(len(ti._line_cache), size, 'oversized transcripts must bypass caching')

    def test_replacing_transcript_discards_old_cached_versions(self):
        for n in range(20):
            ti.save(self.data, self.src, [(1, 2, str(n))])
            self.assertEqual(ti.load(self.data, self.src), [(1, 2, str(n))])
        self.assertEqual(len(ti._line_cache), 1)
