"""Profiles survive restarts and never borrow another channel's credentials."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from store import Store
from profile_accounts import ProfileAccounts, ProfileSettings
import youtube as yt
from scripts import clipper


class Profiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'test.db'
        self.store = Store(self.path)

    def test_legacy_database_migrates_projects_and_retains_credentials(self):
        old = Path(self.tmp.name) / 'old.db'
        with sqlite3.connect(old) as db:
            db.execute('CREATE TABLE projects (name TEXT PRIMARY KEY,data TEXT NOT NULL,updated_at REAL NOT NULL)')
            db.execute('INSERT INTO projects VALUES (?,?,?)', ('old', json.dumps({'clips':[{'caption':'keep'}]}), 123))
            db.execute('CREATE TABLE settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute('INSERT INTO settings VALUES (?,?)', (yt.TOKEN_KEY,json.dumps({'refresh_token':'legacy'})))
        migrated = Store(old)
        self.assertEqual(migrated.project_profile('old'),'default')
        self.assertEqual(migrated.get_project('old')['clips'][0]['caption'],'keep')
        self.assertEqual(migrated.recent_projects(None,'default')[0]['updated_at'],123)
        self.assertEqual(ProfileSettings(migrated,'default').get_setting(yt.TOKEN_KEY),{'refresh_token':'legacy'})
        self.assertEqual(len(Store(old).list_profiles()),1)

    def test_create_move_and_save_keep_ownership_after_restart(self):
        gaming = self.store.create_profile('Gaming')
        self.store.create_project('old',{'clips':[{}]})
        self.store.create_project('new',{'clips':[]},gaming['id'])
        self.assertEqual(self.store.list_projects(gaming['id']),['new'])
        self.store.move_project('old',gaming['id'])
        self.store.put_project('old',{'clips':[{},{}]})
        restarted = Store(self.path)
        self.assertEqual(restarted.project_profile('old'),gaming['id'])
        self.assertEqual(restarted.list_projects('default'),[])
        self.assertEqual({p['name'] for p in restarted.recent_projects(None,gaming['id'])},{'old','new'})
        self.assertEqual(restarted.list_profiles()[1]['projects'],2)
        with self.assertRaises(ValueError): restarted.create_project('bad',{},'missing')
        with self.assertRaises(ValueError): restarted.move_project('old','missing')
        self.assertFalse(restarted.create_project('new',{'clips':[{}]},'default'))
        self.assertEqual(restarted.project_profile('new'),gaming['id'])

    def test_names_are_validated_and_unique(self):
        self.store.create_profile(' Gaming ')
        for name in ('gaming','',' '*3,'x'*61,'bad\nname'):
            with self.assertRaises(ValueError): self.store.create_profile(name)

    def test_disconnect_only_removes_that_profiles_credentials(self):
        gaming = self.store.create_profile('Gaming')['id']
        default = ProfileSettings(self.store,'default')
        other = ProfileSettings(self.store,gaming)
        default.set_setting(yt.TOKEN_KEY,{'refresh_token':'default'})
        other.set_setting(yt.TOKEN_KEY,{'refresh_token':'gaming'})
        other.set_setting(yt.CHANNEL_KEY,{'name':'Gaming'})
        accounts = ProfileAccounts(self.store,'missing.json',Mock())
        accounts.publisher(gaming).disconnect()
        self.assertEqual(default.get_setting(yt.TOKEN_KEY),{'refresh_token':'default'})
        self.assertIsNone(other.get_setting(yt.TOKEN_KEY))
        self.assertIsNone(other.get_setting(yt.CHANNEL_KEY))
        with self.assertRaises(ValueError): accounts.publisher('unknown')

    def test_oauth_callback_routes_by_state_not_selected_profile(self):
        gaming = self.store.create_profile('Gaming')['id']
        from publisher import Publisher
        default = Publisher(self.store,'missing.json')
        accounts = ProfileAccounts(self.store,'missing.json',default)
        other = accounts.publisher(gaming)
        other.pending['state-for-gaming'] = {'verifier':'test','expires':99999999999}
        with patch.object(other,'finish_connect') as finish, patch.object(default,'finish_connect') as wrong:
            accounts.callback(8765,{'state':['state-for-gaming'],'code':['code']})
            finish.assert_called_once()
            wrong.assert_not_called()

    def test_editor_requests_resolve_project_owner_before_explicit_profile(self):
        gaming = self.store.create_profile('Gaming')['id']
        self.store.create_project('a',{},gaming)
        with patch.object(clipper,'store',self.store):
            self.assertEqual(clipper.request_profile({'project':['a'],'profile':['default']}),gaming)
            with self.assertRaises(ValueError): clipper.request_profile({'profile':['missing']})

    def test_profile_api_does_not_expose_tokens(self):
        from publisher import Publisher
        self.store.set_setting(yt.TOKEN_KEY,{'refresh_token':'secret'})
        accounts = ProfileAccounts(self.store,'missing.json',Publisher(self.store,'missing.json'))
        handler = Mock(path='/api/profiles')
        handler.host_ok.return_value = True
        with patch.object(clipper,'store',self.store), patch.object(clipper,'profile_accounts',accounts):
            clipper.Handler.do_GET(handler)
        payload = handler.send_json.call_args.args[0]
        self.assertTrue(payload[0]['connected'])
        self.assertNotIn('secret',json.dumps(payload))

    def test_home_uses_production_studio_without_sample_data(self):
        handler = Mock(path='/'); handler.host_ok.return_value = True
        clipper.Handler.do_GET(handler)
        handler.serve_file.assert_called_once_with(clipper.UI_DIR/'studio.html','text/html; charset=utf-8')
        source = (clipper.UI_DIR/'studio.js').read_text()
        self.assertNotIn('Ranked highlights',source)
        self.assertIn('/api/profiles',source)
        self.assertIn('/api/project-create',source)
        self.assertIn('/api/project-profile',source)

    def test_create_and_move_routes_validate_profile(self):
        gaming = self.store.create_profile('Gaming')['id']
        def post(path, body):
            handler = Mock(path=path)
            handler.host_ok.return_value = handler.origin_ok.return_value = True
            handler.read_json.return_value = body
            with patch.object(clipper,'store',self.store):
                clipper.Handler.do_POST(handler)
            return handler.send_json.call_args
        self.assertEqual(post('/api/project-create',{'name':'project','profile':gaming}).args[0],{'name':'project'})
        self.assertEqual(self.store.project_profile('project'),gaming)
        self.assertEqual(post('/api/project-create',{'name':'invalid','profile':'missing'}).args[1],400)
        post('/api/project-profile',{'name':'project','profile':'default'})
        self.assertEqual(self.store.project_profile('project'),'default')
        self.assertEqual(post('/api/project-create',{'name':'project','profile':gaming}).args[1],409)

    def test_saving_an_existing_project_cannot_change_its_owner(self):
        gaming = self.store.create_profile('Gaming')['id']
        self.store.create_project('project',{'clips':[]},gaming)
        handler = Mock(path='/api/project/project?profile=default')
        handler.host_ok.return_value = handler.origin_ok.return_value = True
        handler.read_json.return_value = {'name':'project','clips':[]}
        with patch.object(clipper,'store',self.store):
            clipper.Handler.do_PUT(handler)
        self.assertEqual(self.store.project_profile('project'),gaming)
        self.assertEqual(handler.send_json.call_args.args[1],409)
        self.assertEqual(self.store.get_project('project'),{'clips':[]})

    def test_new_editor_project_uses_explicit_profile(self):
        gaming = self.store.create_profile('Gaming')['id']
        handler = Mock(path='/api/project/new?profile='+gaming)
        handler.host_ok.return_value = handler.origin_ok.return_value = True
        handler.read_json.return_value = {'name':'new','clips':[]}
        with patch.object(clipper,'store',self.store):
            clipper.Handler.do_PUT(handler)
        self.assertEqual(self.store.project_profile('new'),gaming)

    def test_settings_persist_and_only_new_projects_inherit_defaults(self):
        gaming = self.store.create_profile('Gaming')['id']
        defaults = {'format':'1:1','capSize':64,'normalize':True,'watermark':False}
        self.store.create_project('existing', {'format':'9:16'}, gaming)
        self.store.update_profile(gaming, 'Streams', defaults)
        self.assertEqual(Store(self.path).get_profile(gaming)['name'], 'Streams')
        self.assertEqual(Store(self.path).profile_defaults(gaming), defaults)
        handler = Mock(path='/api/project-create')
        handler.host_ok.return_value = handler.origin_ok.return_value = True
        handler.read_json.return_value = {'name':'new','profile':gaming}
        with patch.object(clipper, 'store', self.store):
            clipper.Handler.do_POST(handler)
        project = self.store.get_project('new')
        for key,value in defaults.items(): self.assertEqual(project[key], value)
        self.assertEqual(self.store.get_project('existing'), {'format':'9:16'})
        self.assertEqual(self.store.profile_defaults('default')['format'], '9:16')

    def test_invalid_settings_and_duplicate_name_are_atomic(self):
        gaming = self.store.create_profile('Gaming')['id']
        defaults = self.store.profile_defaults(gaming)
        for name, values in [('Default',defaults), ('',defaults), ('Changed',dict(defaults,capSize=999)), ('Changed',dict(defaults,normalize='yes'))]:
            with self.assertRaises(ValueError): self.store.update_profile(gaming,name,values)
        self.assertEqual(self.store.get_profile(gaming)['name'], 'Gaming')
        self.assertEqual(self.store.profile_defaults(gaming), defaults)

    def test_delete_requires_empty_nondefault_and_clears_only_its_settings(self):
        gaming = self.store.create_profile('Gaming')['id']
        other = self.store.create_profile('Other')['id']
        self.store.create_project('owned',{},gaming)
        ProfileSettings(self.store,gaming).set_setting(yt.TOKEN_KEY,{'refresh_token':'remove'})
        ProfileSettings(self.store,other).set_setting(yt.TOKEN_KEY,{'refresh_token':'keep'})
        self.store.update_profile(gaming,'Gaming',self.store.profile_defaults(gaming))
        with self.assertRaises(ValueError): self.store.delete_profile('default')
        with self.assertRaises(ValueError): self.store.delete_profile(gaming)
        self.assertIsNotNone(self.store.get_profile(gaming))
        self.store.move_project('owned',other)
        self.store.delete_profile(gaming)
        self.assertIsNone(self.store.get_profile(gaming))
        self.assertIsNone(ProfileSettings(self.store,gaming).get_setting(yt.TOKEN_KEY))
        self.assertEqual(ProfileSettings(self.store,other).get_setting(yt.TOKEN_KEY),{'refresh_token':'keep'})
        self.assertIsNone(self.store.get_setting(f'profile_defaults:{gaming}'))
