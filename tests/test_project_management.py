import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from store import Store


class ProjectManagement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'test.db')
        self.profile = self.store.create_profile('Gaming')['id']
        self.data = {'name': 'original', 'clips': [{'src': '/media/source.mp4', 'in': 2}], 'audio': [{'volume': .5}]}
        self.store.create_project('original', self.data, self.profile)
        self.store.claim_video('/media/source.mp4', 'original')
        self.store.replace_favorites_for('original', [{'src': '/media/source.mp4'}])
        self.store.mark_own_media('original')

    def test_rename_preserves_assets_and_profile(self):
        self.store.manage_project('original', 'renamed')
        self.assertIsNone(self.store.get_project('original'))
        self.assertEqual(self.store.get_project('renamed'), dict(self.data, name='renamed'))
        self.assertEqual(self.store.project_profile('renamed'), self.profile)
        self.assertEqual(self.store.video_owners()['/media/source.mp4'], {'renamed'})
        self.assertEqual(len(self.store.list_favorites('renamed')), 1)
        self.assertTrue(self.store.own_media('renamed'))

    def test_duplicate_is_independent_and_delete_keeps_original(self):
        self.store.manage_project('original', 'copy', duplicate=True)
        data = self.store.get_project('copy')
        data['clips'].clear()
        self.store.put_project('copy', data)
        self.assertEqual(len(self.store.get_project('original')['clips']), 1)
        self.assertEqual(self.store.project_profile('copy'), self.profile)
        self.assertEqual(len(self.store.list_favorites('copy')), 1)
        self.store.delete_project('copy')
        self.assertEqual(self.store.video_owners()['/media/source.mp4'], {'original'})
        self.assertEqual(len(self.store.list_favorites('original')), 1)

    def test_conflict_and_missing_source_leave_data_untouched(self):
        self.store.create_project('taken', {'name': 'taken'})
        for source, target in [('original', 'taken'), ('missing', 'new')]:
            with self.assertRaises(ValueError):
                self.store.manage_project(source, target)
        self.assertEqual(self.store.get_project('original'), self.data)
        self.assertEqual(self.store.get_project('taken'), {'name': 'taken'})
        self.assertIsNone(self.store.get_project('new'))
