import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class TranscribeConcurrency(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.src = Path(tmp.name) / 'source.mp4'
        self.src.write_bytes(b'video')
        self.release = threading.Event()
        self.threads = []
        real_thread = threading.Thread
        self.thread_class = real_thread
        def spawn(*args, **kwargs):
            thread = real_thread(*args, **kwargs)
            self.threads.append(thread)
            return thread
        for name, value in [('transcripts', {}), ('_pending_transcribes', {})]:
            patch = mock.patch.object(clipper, name, value, create=True)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(clipper, 'speech_engine', return_value='fast')
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(clipper.threading, 'Thread', side_effect=spawn)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.finish)

    def finish(self):
        self.release.set()
        for thread in self.threads:
            if thread.ident is not None:
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())

    def listen(self, job_id, *args):
        if not self.release.wait(timeout=5):
            raise RuntimeError('test release timed out')
        clipper.transcripts[job_id] = {'id': job_id, 'state': 'done', 'text': 'Hello'}

    def test_simultaneous_requests_share_one_listening_job(self):
        gate = threading.Barrier(8)
        def request(_):
            gate.wait(timeout=5)
            return clipper.start_transcribe(str(self.src), 0., 2., True, 'translate')
        with mock.patch.object(clipper, 'listen', side_effect=self.listen) as listen:
            with ThreadPoolExecutor(max_workers=8) as pool:
                jobs = list(pool.map(request, range(8)))
            self.finish()
            self.assertEqual(listen.call_count, 1)
        self.assertEqual(len({job['id'] for job in jobs}), 1)
        self.assertTrue(all(clipper.transcripts[job['id']]['state'] == 'done' for job in jobs))
        self.assertEqual(clipper._pending_transcribes, {})

    def test_ranges_modes_tasks_and_changed_source_versions_stay_separate(self):
        with mock.patch.object(clipper, 'listen', side_effect=self.listen) as listen:
            jobs = [clipper.start_transcribe(str(self.src), 0., 2., True, 'translate')]
            duplicate = clipper.start_transcribe(str(self.src), 0., 2., True, 'translate')
            jobs.extend([
                clipper.start_transcribe(str(self.src), 1., 3., True, 'translate'),
                clipper.start_transcribe(str(self.src), 0., 2., False, 'translate'),
                clipper.start_transcribe(str(self.src), 0., 2., True, 'transcribe'),
            ])
            self.src.write_bytes(b'changed source')
            jobs.append(clipper.start_transcribe(str(self.src), 0., 2., True, 'translate'))
            self.finish()
            self.assertEqual(listen.call_count, 5)
        self.assertEqual(duplicate['id'], jobs[0]['id'])
        self.assertEqual(len({job['id'] for job in jobs}), 5)

    def test_finished_and_failed_jobs_are_not_reused(self):
        self.release.set()
        attempts = 0
        def attempt(job_id, *args):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError('failed')
            self.listen(job_id, *args)
        with mock.patch.object(clipper, 'listen', side_effect=attempt) as listen:
            first = clipper.start_transcribe(str(self.src), 0., 2., True)
            self.finish()
            self.assertEqual(clipper.transcripts[first['id']]['state'], 'error')
            self.assertEqual(clipper._pending_transcribes, {})
            second = clipper.start_transcribe(str(self.src), 0., 2., True)
            self.finish()
            self.assertNotEqual(first['id'], second['id'])
            self.assertEqual(listen.call_count, 2)
            self.assertEqual(clipper.transcripts[second['id']]['state'], 'done')
            third = clipper.start_transcribe(str(self.src), 0., 2., True)
            self.finish()
            self.assertNotEqual(second['id'], third['id'])
            self.assertEqual(listen.call_count, 3)

    def test_different_files_can_listen_concurrently(self):
        other = self.src.with_name('other.mp4')
        other.write_bytes(b'other')
        gate = threading.Barrier(2)
        def listen(job_id, *args):
            gate.wait(timeout=5)
            clipper.transcripts[job_id] = {'id': job_id, 'state': 'done'}
        with mock.patch.object(clipper, 'listen', side_effect=listen):
            jobs = [clipper.start_transcribe(str(src), 0., 2., True) for src in [self.src, other]]
            self.finish()
        self.assertTrue(all(clipper.transcripts[job['id']]['state'] == 'done' for job in jobs))

    def test_thread_start_failure_clears_pending_job_and_allows_retry(self):
        with mock.patch.object(self.thread_class, 'start', side_effect=OSError('cannot start')):
            with self.assertRaisesRegex(OSError, 'cannot start'):
                clipper.start_transcribe(str(self.src), 0., 2., True)
        self.assertEqual(clipper._pending_transcribes, {})
        self.assertTrue(all(job['state'] == 'error' for job in clipper.transcripts.values()))
        self.release.set()
        with mock.patch.object(clipper, 'listen', side_effect=self.listen):
            job = clipper.start_transcribe(str(self.src), 0., 2., True)
            self.finish()
        self.assertEqual(clipper.transcripts[job['id']]['state'], 'done')

    def test_missing_speech_engine_keeps_existing_error_without_starting_work(self):
        with mock.patch.object(clipper, 'speech_engine', return_value=None), mock.patch.object(clipper.embedded_subs, 'has_subtitles', return_value=False):
            result = clipper.start_transcribe(str(self.src), 0., 2., True)
        self.assertEqual(result, {'state': 'error', 'message': clipper.WHISPER_HINT})
        self.assertEqual(self.threads, [])
        self.assertEqual(clipper._pending_transcribes, {})
