import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper
from store import Store


class ProjectBatchLoadingTests(unittest.TestCase):
    def test_range_discovery_uses_one_project_read_instead_of_one_per_project(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'data.db')
            for i in range(100):
                store.put_project(f'{i:03}', {'clips': [{'src': 'source', 'in': i, 'out': i + 1}],
                                             'bank': [{'src': 'source', 'in': i, 'out': i + 1}]})
            store.replace_favorites([{'src': 'saved', 'in': 1, 'out': 2}])
            with mock.patch.object(clipper, 'store', store), mock.patch.object(store, '_db', wraps=store._db) as connect:
                ranges = clipper.all_clip_ranges()
            self.assertEqual(ranges, [('source', float(i), float(i + 1)) for i in range(100)] + [('saved', 1., 2.)])
            self.assertEqual(connect.call_count, 2, 'one project query plus one Saved query')
