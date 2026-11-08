from contextlib import closing
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from store import Store


class FavoritesQueryPerformance(unittest.TestCase):
    def test_project_reads_do_not_scan_other_projects_saved_clips(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'bench.db')
            shared = [{'src': f'shared{i}'} for i in range(5)]
            owned = [{'src': f'mine{i}'} for i in range(3)]
            with store._db() as db:
                db.executemany('INSERT INTO favorites(data,project) VALUES (?,?)',
                               [(json.dumps({'src': f'other{i}'}), f'project{i % 100}') for i in range(20000)]
                               + [(json.dumps(item), None) for item in shared]
                               + [(json.dumps(item), 'mine') for item in owned])
            original = store._db
            steps = 0

            def count():
                nonlocal steps
                steps += 1
                return 0

            def session():
                db = original()
                db.conn.set_progress_handler(count, 1)
                return db

            with patch.object(store, '_db', side_effect=session):
                self.assertEqual(store.list_favorites('mine'), shared + owned)
            self.assertLess(steps, 1000,
                            'a small visible Saved list must not walk 20,000 unrelated rows')
            self.assertEqual(len(store.list_favorites()), 20008,
                             'unscoped callers must still see every clip')

    def test_legacy_favorites_table_migrates_before_index_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'legacy.db'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE favorites(id INTEGER PRIMARY KEY AUTOINCREMENT,data TEXT NOT NULL)')
                db.execute('INSERT INTO favorites(data) VALUES (?)', (json.dumps({'src': 'legacy'}),))
                db.commit()
            store = Store(path)
            self.assertEqual(store.list_favorites('new-project'), [{'src': 'legacy'}])
            store.replace_favorites_for('new-project', [{'src': 'legacy'}, {'src': 'mine'}])
            self.assertEqual(store.list_favorites('other-project'), [{'src': 'legacy'}])
