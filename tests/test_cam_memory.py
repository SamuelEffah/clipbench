import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import cam_memory  # noqa: E402
from scripts import clipper  # noqa: E402

CAM = {"x": 0.0, "y": 0.608, "w": 0.29, "h": 0.39}


class StreamKey(unittest.TestCase):
    def test_recordings_of_one_stream_share_a_key(self):
        self.assertEqual(cam_memory.stream_key("clips/SPECTACULAR_SUNDAY_STREAM-174158.mp4"), cam_memory.stream_key("clips/SPECTACULAR_SUNDAY_STREAM-190505.mp4"))

    def test_different_videos_have_different_keys(self):
        self.assertNotEqual(cam_memory.stream_key("clips/SPECTACULAR_SUNDAY_STREAM-174158.mp4"), cam_memory.stream_key("clips/In_the_Chair_Tabitha_JK-za01EK_AcKs.mp4"))
        self.assertNotEqual(cam_memory.stream_key("clips/Talk-abcdefghijk.mp4"), cam_memory.stream_key("clips/Talk-lmnopqrstuv.mp4"))
        self.assertNotEqual(cam_memory.stream_key("data/live/rec-1762500000.ts"), cam_memory.stream_key("data/live/rec-1762590000.ts"))

    def test_uploads_of_one_show_share_a_key(self):
        self.assertEqual(cam_memory.stream_key("clips/SPECTACULAR_SUNDAY_STREAM-za01EK_AcKs.mp4"), cam_memory.stream_key("clips/SPECTACULAR_SUNDAY_STREAM-joXwQ9tHX3U.mp4"))


class Memory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.memory = cam_memory.CamMemory(Path(self.tmp.name) / "cams.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_cam_found_in_one_recording_is_recalled_for_another_of_the_same_stream(self):
        self.memory.remember("clips/STREAM-174158.mp4", 1920, 1080, CAM)
        self.assertEqual(self.memory.recall("clips/STREAM-190505.mp4", 1920, 1080), CAM)

    def test_nothing_is_recalled_for_another_stream_or_another_picture_size(self):
        self.memory.remember("clips/STREAM-174158.mp4", 1920, 1080, CAM)
        self.assertIsNone(self.memory.recall("clips/OTHER-174158.mp4", 1920, 1080))
        self.assertIsNone(self.memory.recall("clips/STREAM-190505.mp4", 1280, 720))

    def test_a_later_find_replaces_the_earlier_one(self):
        self.memory.remember("clips/STREAM-174158.mp4", 1920, 1080, CAM)
        self.memory.remember("clips/STREAM-190505.mp4", 1920, 1080, {**CAM, "y": 0.5})
        self.assertEqual(self.memory.recall("clips/STREAM-174158.mp4", 1920, 1080)["y"], 0.5)

    def test_a_damaged_file_is_treated_as_empty(self):
        self.memory.path.write_text("{not json")
        self.assertIsNone(self.memory.recall("clips/STREAM-174158.mp4", 1920, 1080))
        self.memory.remember("clips/STREAM-174158.mp4", 1920, 1080, CAM)
        self.assertEqual(self.memory.recall("clips/STREAM-174158.mp4", 1920, 1080), CAM)


class LayoutRoute(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.memory = cam_memory.CamMemory(Path(self.tmp.name) / "cams.json")

    def tearDown(self):
        self.tmp.cleanup()

    def analyze(self, answers):
        calls = []

        def fake(src, start, end, remembered=None):
            calls.append(remembered)
            return answers.pop(0)
        return fake, calls

    def test_a_border_found_cam_is_remembered_and_offered_to_the_next_clip_of_the_stream(self):
        first = {"layout": "webcam", "faces": [], "webcam": CAM, "guessed": False, "share": 1.0, "reason": "", "segments": []}
        second = {"layout": "webcam", "faces": [], "webcam": CAM, "remembered": True, "reason": "", "segments": []}
        fake, calls = self.analyze([first, second])
        with mock.patch.object(clipper, "cams", self.memory), mock.patch.object(clipper.auto_layout, "analyze", fake), \
                mock.patch.object(clipper.auto_layout, "available", lambda: True), mock.patch.object(clipper.reframe, "probe_size", lambda src: (1920, 1080)):
            clipper.layout_analysis("clips/STREAM-174158.mp4", 0, 10)
            found = clipper.layout_analysis("clips/STREAM-190505.mp4", 0, 10)
        self.assertEqual(calls, [None, CAM])
        self.assertEqual(found["width"], 1920)

    def test_a_guessed_or_remembered_cam_is_not_saved(self):
        guessed = {"layout": "webcam", "faces": [], "webcam": CAM, "guessed": True, "share": 1.0, "reason": "", "segments": []}
        fake, calls = self.analyze([guessed])
        with mock.patch.object(clipper, "cams", self.memory), mock.patch.object(clipper.auto_layout, "analyze", fake), \
                mock.patch.object(clipper.auto_layout, "available", lambda: True), mock.patch.object(clipper.reframe, "probe_size", lambda src: (1920, 1080)):
            clipper.layout_analysis("clips/STREAM-174158.mp4", 0, 10)
        self.assertIsNone(self.memory.recall("clips/STREAM-174158.mp4", 1920, 1080))


if __name__ == "__main__":
    unittest.main()
