import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from scripts import clipper, make_short, voice_isolation  # noqa: E402

O = make_short.DEFAULT_OPTIONS


def loudness(path, start=0, length=1):
    out = subprocess.run(["ffmpeg", "-v", "info", "-ss", str(start), "-t", str(length), "-i", path, "-vn", "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return float(re.search(r"mean_volume: (\S+)", out).group(1))


class VoiceFileTests(unittest.TestCase):
    def test_the_same_clip_always_finds_the_same_file(self):
        a = voice_isolation.cached_path("/v", "/x/a.mkv", 1.0, 5.0)
        self.assertEqual(a, voice_isolation.cached_path("/v", "/x/a.mkv", 1.0, 5.0))
        self.assertNotEqual(a, voice_isolation.cached_path("/v", "/x/a.mkv", 1.0, 5.5))
        self.assertNotEqual(a, voice_isolation.cached_path("/v", "/x/b.mkv", 1.0, 5.0))

    def test_a_clip_is_matched_to_the_range_the_cut_list_writes(self):
        self.assertEqual(clipper.rounded_range(864.1112289, 874.4155376), (864.11, 874.42))

    def test_a_voice_that_is_not_there_is_refused_by_the_cut_list(self):
        with self.assertRaises(SystemExit):
            make_short.read_cuts("@voice /nowhere/voice.wav\n0:00 - 0:02")


@unittest.skipUnless(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode == 0, "ffmpeg isn't installed")
class VoiceRenderTests(unittest.TestCase):
    def test_a_clip_with_a_voice_takes_its_sound_from_that_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, voice, dest = (str(Path(tmp) / n) for n in ("src.mp4", "voice.wav", "out.mp4"))
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=160x120:r=30:d=4", "-f", "lavfi",
                            "-i", "anullsrc=r=44100:cl=stereo", "-t", "4", "-pix_fmt", "yuv420p", src], check=True)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=500:duration=2", "-ac", "2", voice], check=True)
            cuts = [(0, 2, None), (2, 4, None)]
            opts = [{**O, "voice": voice}, dict(O)]
            make_short.build_montage(src, cuts, 0, dest, opts)
            self.assertGreater(loudness(dest, 0.2, 1.2), -30)
            self.assertLess(loudness(dest, 2.2, 1.5), -60)

    def test_a_voice_survives_a_speed_ramp(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, voice, dest = (str(Path(tmp) / n) for n in ("src.mp4", "voice.wav", "out.mp4"))
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=160x120:r=30:d=4", "-f", "lavfi",
                            "-i", "anullsrc=r=44100:cl=stereo", "-t", "4", "-pix_fmt", "yuv420p", src], check=True)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=500:duration=3", "-ac", "2", voice], check=True)
            ramp = next(r for r in make_short.RAMPS if r != "none")
            make_short.build_montage(src, [(0, 3, None)], 0, dest, [{**O, "voice": voice, "ramp": ramp}])
            self.assertGreater(loudness(dest, 0.3, 1), -30)


if __name__ == "__main__":
    unittest.main()
