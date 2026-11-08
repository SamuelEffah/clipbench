import copy
import sys
import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class PreviewResultReuseTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.src = self.root / 'source.mp4'
        self.src.write_bytes(b'source')
        self.voice = self.root / 'voice.wav'
        self.voice.write_bytes(b'voice')
        self.project = {'clips': [{'src': str(self.src), 'in': 0, 'out': 2, 'capScale': 1.5}, {'src': str(self.src), 'in': 2, 'out': 4}]}
        def render(key, hook, folder, flags, cuts, out):
            out.write_bytes(b'preview')
            clipper.renders[key] = {'state': 'done', 'stamp': 123, 'pct': 100}
        def thread(*, target, args, **kwargs):
            return mock.Mock(start=lambda: target(*args))
        for name, value in [('PREVIEW_DIR', self.root), ('renders', {}), ('_preview_results', OrderedDict())]:
            patch = mock.patch.object(clipper, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(clipper, 'run_render', side_effect=render)
        self.render = patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(clipper.threading, 'Thread', side_effect=thread)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(clipper.voice_isolation, 'cached_path', return_value=self.voice)
        patch.start()
        self.addCleanup(patch.stop)

    def preview(self):
        return clipper.start_preview('demo', self.project, 1)

    def test_repeat_preview_reuses_render_but_settings_and_files_invalidate(self):
        self.assertEqual(self.preview()['state'], 'done')
        with mock.patch.object(clipper, 'export_cuts', side_effect=AssertionError('cache hit must not prepare another render')):
            for _ in range(20):
                self.assertEqual(self.preview()['state'], 'done')
        self.assertEqual(self.render.call_count, 1)
        self.project['clips'][0]['capScale'] = 2
        self.preview()
        self.assertEqual(self.render.call_count, 2, 'inherited caption style invalidates')
        self.project['clips'][1]['effect'] = 'bw'
        self.preview()
        self.src.write_bytes(b'changed source')
        self.preview()
        self.assertEqual(self.render.call_count, 4)
        self.project['clips'][1]['voice'] = True
        self.preview()
        self.voice.write_bytes(b'changed voice')
        self.preview()
        self.assertEqual(self.render.call_count, 6)
        clipper.preview_path('demo').unlink()
        self.preview()
        self.assertEqual(self.render.call_count, 7)
        clipper.preview_path('demo').write_bytes(b'external replacement')
        self.preview()
        self.assertEqual(self.render.call_count, 8)

    def test_failed_or_changed_during_render_results_are_not_reused(self):
        def fail(*args):
            clipper.renders['demo~clip'] = {'state': 'error'}
        self.render.side_effect = fail
        self.preview()
        self.preview()
        self.assertEqual(self.render.call_count, 2)
        def change(key, hook, folder, flags, cuts, out):
            out.write_bytes(b'preview')
            self.src.write_bytes(self.src.read_bytes() + b'x')
            clipper.renders[key] = {'state': 'done'}
        self.render.side_effect = change
        self.preview()
        self.preview()
        self.assertEqual(self.render.call_count, 4)
        self.assertFalse(clipper._preview_results)

    def test_saved_source_replacement_and_cache_bound(self):
        saved = self.root / 'saved.mp4'
        saved.write_bytes(b'saved')
        self.src.unlink()
        with mock.patch.object(clipper, 'indexed_cut', return_value='saved'), mock.patch.object(clipper, 'cut_path', return_value=saved), mock.patch.object(clipper, 'probe', return_value={'duration': 2}):
            self.preview()
            self.preview()
            self.assertEqual(self.render.call_count, 1)
            saved.write_bytes(b'updated saved file')
            self.preview()
            self.assertEqual(self.render.call_count, 2)
            for i in range(clipper.PREVIEW_CACHE_LIMIT + 3):
                clipper.start_preview(f'project{i}', self.project, 1)
            self.assertEqual(len(clipper._preview_results), clipper.PREVIEW_CACHE_LIMIT)

    def test_timeline_markers_names_and_locks_do_not_restart_the_encoder(self):
        self.preview()
        for i in range(24):
            self.project.update(markers=[i / 10], laneName={'top': f'Lane {i}'},
                                laneLock={'top': bool(i % 2)})
            self.assertEqual(self.preview()['state'], 'done')
        self.assertEqual(self.render.call_count, 1,
                         'timeline-only changes cannot affect preview video or audio')
        self.project['laneMute'] = {'top': True}
        self.preview()
        self.assertEqual(self.render.call_count, 2, 'audible lane changes must invalidate')
