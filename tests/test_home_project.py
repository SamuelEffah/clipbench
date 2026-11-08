import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from store import Store


class HomeProject(unittest.TestCase):
    def test_resume_prefers_last_opened_with_recent_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'test.db')
            self.assertIsNone(store.home_project())
            thumb='/clip-thumb/'+'a'*64+'.jpg'
            with patch('store.time.time',return_value=10):
                store.put_project('older',{'clips':[{'thumb':thumb,'src':'private-source'}]})
            with patch('store.time.time',return_value=20):
                store.put_project('recent',{'clips':[]})
            self.assertEqual(store.home_project('missing')['name'],'recent')
            self.assertEqual(store.home_project('older'),{'name':'older','updated_at':10,'thumb':thumb})
            store.delete_project('older')
            self.assertEqual(store.home_project('older')['name'],'recent')

    def test_recent_projects_newest_first_with_clip_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'test.db')
            self.assertEqual(store.recent_projects(),[])
            thumb='/clip-thumb/'+'b'*64+'.jpg'
            for name,at,clips in (('a',1,[]),('b',3,[{'thumb':thumb},{}]),('c',2,[{}]),('d',0,[])):
                with patch('store.time.time',return_value=at):
                    store.put_project(name,{'clips':clips})
            got=store.recent_projects(3)
            self.assertEqual([p['name'] for p in got],['b','c','a'])
            self.assertEqual((got[0]['clips'],got[0]['thumb']),(2,thumb))
            self.assertIsNone(got[1]['thumb'])
            self.assertIn('src',got[1])

    def test_create_never_overwrites_existing_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'test.db')
            self.assertTrue(store.create_project('named',{'clips':[{'caption':'keep'}]}))
            self.assertFalse(store.create_project('named',{'clips':[]}))
            self.assertEqual(store.get_project('named')['clips'],[{'caption':'keep'}])
