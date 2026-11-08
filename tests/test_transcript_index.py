import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import clipper  # noqa: E402
import transcript_index as ti  # noqa: E402

RESULT = {"segments": [{"text": " Hello there.", "start": 1.0, "end": 2.5},
                       {"text": "   ", "start": 3.0, "end": 4.0},
                       {"text": " Not from me.", "start": 5.0, "end": 5.0},
                       {"text": " Mumen Rider is here!", "start": 6.0, "end": 8.0}]}


class Cues(unittest.TestCase):
    def test_segments_become_lines_and_empty_or_zero_length_ones_are_dropped(self):
        self.assertEqual(ti.cues_from(RESULT), [(1.0, 2.5, "Hello there."), (6.0, 8.0, "Mumen Rider is here!")])

    def test_no_segments(self):
        self.assertEqual(ti.cues_from({}), [])


class Store(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.video = Path(self.dir.name) / "ep.mp4"
        self.video.write_bytes(b"video")
        self.data = Path(self.dir.name) / "data"

    def tearDown(self):
        self.dir.cleanup()

    def test_nothing_saved_loads_none(self):
        self.assertIsNone(ti.load(self.data, str(self.video)))

    def test_saved_cues_load_back_as_tuples(self):
        ti.save(self.data, str(self.video), [(1.0, 2.0, "hi")])
        self.assertEqual(ti.load(self.data, str(self.video)), [(1.0, 2.0, "hi")])

    def test_a_video_with_no_speech_is_saved_as_heard_and_empty(self):
        ti.save(self.data, str(self.video), [])
        self.assertEqual(ti.load(self.data, str(self.video)), [])

    def test_a_replaced_video_invalidates_the_transcript(self):
        ti.save(self.data, str(self.video), [(1.0, 2.0, "hi")])
        self.video.write_bytes(b"a different, longer video file")
        self.assertIsNone(ti.load(self.data, str(self.video)))

    def test_a_corrupt_file_loads_none(self):
        ti.save(self.data, str(self.video), [(1.0, 2.0, "hi")])
        next(self.data.glob("transcripts/*.json")).write_text("{nope")
        self.assertIsNone(ti.load(self.data, str(self.video)))


class Build(unittest.TestCase):
    def test_listens_once_and_saves_what_was_heard(self):
        with tempfile.TemporaryDirectory() as d:
            video, data = Path(d) / "ep.mp4", Path(d) / "data"
            video.write_bytes(b"v")
            seen = []
            cues = ti.build(data, str(video), lambda src: seen.append(src) or RESULT)
            self.assertEqual(cues, ti.load(data, str(video)))
            self.assertEqual(len(cues), 2)
            self.assertEqual(seen, [str(video)])

    def test_a_failed_listen_saves_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            video, data = Path(d) / "ep.mp4", Path(d) / "data"
            video.write_bytes(b"v")
            with self.assertRaises(RuntimeError):
                ti.build(data, str(video), lambda src: (_ for _ in ()).throw(RuntimeError("no audio")))
            self.assertIsNone(ti.load(data, str(video)))


class Server(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.video = Path(self.dir.name) / "ep9.mp4"
        self.video.write_bytes(b"v")
        patches = [mock.patch.object(clipper, "DATA_DIR", Path(self.dir.name) / "data"),
                   mock.patch.object(clipper, "registry", {"aaaaaaaaaaaa": self.video}),
                   mock.patch.object(clipper, "index_jobs", {}),
                   mock.patch.object(clipper, "scan_library", lambda project=None: [{"id": "aaaaaaaaaaaa", "broll": False}]),
                   mock.patch.object(clipper, "probe", lambda src: {"duration": 100.0}),
                   mock.patch.object(clipper.embedded_subs, "all_cues", lambda src: None)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.dir.cleanup)

    def test_a_video_never_listened_to_is_offered_for_listening(self):
        got = clipper.search_dialogue("mumen")
        self.assertEqual((got["results"], got["videos"]), ([], 0))
        self.assertEqual(got["unheard"], [{"id": "aaaaaaaaaaaa", "name": "ep9.mp4", "working": False}])

    def test_a_listened_video_is_searched_and_no_longer_offered(self):
        ti.save(clipper.DATA_DIR, self.video, [(10.0, 12.0, "Mumen Rider is here!")])
        got = clipper.search_dialogue("mumen rider")
        self.assertEqual(got["unheard"], [])
        self.assertEqual([r["text"] for r in got["results"]], ["Mumen Rider is here!"])

    def test_a_video_being_listened_to_says_so(self):
        clipper.index_jobs["aaaaaaaaaaaa"] = {"state": "working"}
        self.assertTrue(clipper.search_dialogue("x y")["unheard"][0]["working"])

    def test_embedded_subtitles_win_over_a_transcript(self):
        ti.save(clipper.DATA_DIR, self.video, [(1.0, 2.0, "heard")])
        with mock.patch.object(clipper.embedded_subs, "all_cues", lambda src: [(1.0, 2.0, "subtitled")]):
            self.assertEqual(clipper.dialogue_cues(self.video), [(1.0, 2.0, "subtitled")])

    def test_listening_that_fails_ends_the_job_with_a_message(self):
        with mock.patch.object(clipper, "listen_whole", side_effect=RuntimeError("no audio")):
            clipper.run_index("aaaaaaaaaaaa")
        job = clipper.index_jobs["aaaaaaaaaaaa"]
        self.assertEqual(job["state"], "error")
        self.assertIn("no audio", job["message"])

    def test_listening_that_works_saves_the_transcript(self):
        with mock.patch.object(clipper, "listen_whole", return_value=RESULT):
            clipper.run_index("aaaaaaaaaaaa")
        self.assertEqual(clipper.index_jobs["aaaaaaaaaaaa"], {"state": "ready"})
        self.assertEqual(len(clipper.dialogue_cues(self.video)), 2)

    def test_an_unknown_video_cannot_be_listened_to(self):
        self.assertEqual(clipper.start_index("bbbbbbbbbbbb")["state"], "error")


if __name__ == "__main__":
    unittest.main()
