import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import make_short as ms


class ScratchCodec(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, ms, "_hardware_h264", ms._hardware_h264)

    def test_uses_hardware_encoder_when_present(self):
        ms._hardware_h264 = True
        flags = ms.scratch_codec()
        self.assertEqual(flags[:2], ["-c:v", "h264_videotoolbox"])
        self.assertIn(ms.SCRATCH_BITRATE, flags)

    def test_falls_back_to_x264(self):
        ms._hardware_h264 = False
        self.assertEqual(ms.scratch_codec(), ["-c:v", "libx264", "-preset", "fast", "-crf", "16"])

    def test_lookup_runs_once(self):
        ms._hardware_h264 = None
        out = mock.Mock(stdout=" V....D h264_videotoolbox  VideoToolbox")
        with mock.patch.object(ms.subprocess, "run", return_value=out) as run:
            self.assertTrue(ms.hardware_h264())
            self.assertTrue(ms.hardware_h264())
        self.assertEqual(run.call_count, 1)

    def test_missing_ffmpeg_means_no_hardware(self):
        ms._hardware_h264 = None
        with mock.patch.object(ms.subprocess, "run", side_effect=OSError):
            self.assertFalse(ms.hardware_h264())

    def test_final_render_uses_the_hardware_encoder_at_the_final_bitrate(self):
        ms._hardware_h264 = True
        flags = ms.video_codec("medium", 18)
        self.assertEqual(flags[:2], ["-c:v", "h264_videotoolbox"])
        self.assertIn(ms.FINAL_BITRATE, flags)
        self.assertNotIn(ms.DRAFT_BITRATE, flags)

    def test_final_render_falls_back_to_x264(self):
        ms._hardware_h264 = False
        self.assertEqual(ms.video_codec("medium", 18), ["-c:v", "libx264", "-preset", "medium", "-crf", "18"])

    def test_a_draft_is_smaller_than_a_final(self):
        ms._hardware_h264 = True
        with mock.patch.object(ms, "draft_encode", True):
            self.assertIn(ms.DRAFT_BITRATE, ms.video_codec("medium", 18))
        self.assertLess(int(ms.DRAFT_BITRATE.rstrip("M")), int(ms.FINAL_BITRATE.rstrip("M")))


if __name__ == "__main__":
    unittest.main()
