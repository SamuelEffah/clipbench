import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class CutIndexCacheTests(unittest.TestCase):
    def test_repeated_lookup_reuses_parse_and_detects_external_changes(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(clipper, 'CUT_DIR', Path(folder)):
            path = Path(folder) / 'index.json'
            path.write_text(json.dumps({'source|0.000|1.000': 'a'}))
            (Path(folder) / 'a.mp4').touch()
            original = Path.read_text
            reads = []
            def read(p, *args, **kwargs):
                if p == path:
                    reads.append(p)
                return original(p, *args, **kwargs)
            with patch.object(Path, 'read_text', read):
                for _ in range(100):
                    self.assertEqual(clipper.indexed_cut('source', 0, 1), 'a')
                self.assertEqual(len(reads), 1)
                path.write_text('{}')
                self.assertIsNone(clipper.indexed_cut('source', 0, 1))
                clipper.remember_cut('source', 0, 1, 'a')
                self.assertEqual(clipper.indexed_cut('source', 0, 1), 'a')
                path.unlink()
                self.assertIsNone(clipper.indexed_cut('source', 0, 1))
