import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import clip_moments  # noqa: E402
import clip_motion  # noqa: E402
import suggest  # noqa: E402

SIZE = clip_motion.WIDTH * clip_motion.HEIGHT
PER = 20


def frame(level):
    return bytes([level]) * SIZE


class FromFrames(unittest.TestCase):
    def test_a_still_picture_has_no_motion(self):
        self.assertEqual(clip_motion.from_frames([frame(90)] * 10), [0] * 9)

    def test_a_changing_picture_has_motion_and_a_bigger_change_has_more(self):
        small = clip_motion.from_frames([frame(90), frame(100), frame(90)])
        big = clip_motion.from_frames([frame(90), frame(200), frame(90)])
        self.assertTrue(all(v > 0 for v in small))
        self.assertGreater(min(big), max(small))

    def test_values_stay_between_zero_and_255(self):
        got = clip_motion.from_frames([frame(0), frame(255), frame(0)])
        self.assertTrue(all(0 <= v <= 255 for v in got))

    def test_fewer_than_two_frames_give_nothing(self):
        self.assertEqual(clip_motion.from_frames([]), [])
        self.assertEqual(clip_motion.from_frames([frame(1)]), [])

    def test_a_cut_is_capped_so_one_flash_does_not_set_the_scale(self):
        got = clip_motion.from_frames([frame(0)] * 3 + [frame(255)] * 3)
        self.assertEqual(max(got), 255)
        self.assertEqual(got.count(255), 1)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is needed")
class FromVideo(unittest.TestCase):
    def make(self, tmp, source):
        out = str(Path(tmp) / "v.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source, "-t", "4", "-pix_fmt", "yuv420p", out], check=True)
        return out

    def test_moving_footage_scores_above_still_footage(self):
        with tempfile.TemporaryDirectory() as tmp:
            moving = clip_motion.compute(self.make(tmp, "testsrc=size=320x180:rate=25"))
            still = clip_motion.compute(self.make(tmp, "color=c=gray:size=320x180:rate=25"))
        self.assertEqual(moving["per_sec"], clip_motion.PER_SEC)
        self.assertGreater(len(moving["values"]), 8)
        self.assertGreater(sum(moving["values"]) / len(moving["values"]), 20 + sum(still["values"]) / len(still["values"]))

    def test_a_file_that_is_not_video_gives_no_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "x.mp4"
            bad.write_bytes(b"not a video")
            self.assertEqual(clip_motion.compute(str(bad))["values"], [])


class UsedInRanking(unittest.TestCase):
    def talking(self, duration=120):
        return ([200] * PER + [10] * PER) * (duration // 2)

    def quiet_track(self, duration=120):
        return [100] * int(duration * PER)

    def test_a_busy_picture_wins_when_the_sound_is_flat(self):
        motion = {"per_sec": 4, "values": [10] * 480}
        for i in range(60 * 4, 80 * 4):
            motion["values"][i] = 220
        found = clip_moments.windows(120, [], self.quiet_track(), PER, motion=motion, motion_weight=1.0)
        self.assertTrue(any(w["in"] <= 62 and w["out"] >= 78 for w in found[:3]))

    def test_motion_is_ignored_when_its_weight_is_zero(self):
        motion = {"per_sec": 4, "values": [10] * 240 + [220] * 240}
        plain = clip_moments.windows(120, [], self.quiet_track(), PER)
        weightless = clip_moments.windows(120, [], self.quiet_track(), PER, motion=motion, motion_weight=0.0)
        self.assertEqual(plain, weightless)

    def test_suggest_prefers_the_busy_stretch_of_a_speechless_video(self):
        values = [10] * 480
        for i in range(60 * 4, 80 * 4):
            values[i] = 220
        got = suggest.suggest([], 120, [], self.quiet_track(), PER, motion={"per_sec": 4, "values": values})
        top = got[0]
        self.assertGreaterEqual(min(top["out"], 80) - max(top["in"], 60), 15)
        self.assertIn("motion", top["parts"])

    def test_a_long_stretch_of_action_beats_one_that_is_mostly_frozen(self):
        values = [0] * 800
        for i in range(40 * 4, 70 * 4):
            values[i] = 150
        values[10 * 4] = 255
        got = suggest.suggest([], 200, [], [20] * 4000, PER, motion={"per_sec": 4, "values": values})
        top = got[0]
        self.assertGreaterEqual(min(top["out"], 70) - max(top["in"], 40), 0.8 * (top["out"] - top["in"]))

    def test_the_whole_action_is_offered_not_just_a_piece_of_it(self):
        values = [0] * 800
        for i in range(20 * 4, 50 * 4):
            values[i] = 150
        for i in range(34 * 4, 45 * 4):
            values[i] = 165
        got = suggest.suggest([], 200, [], [20] * 4000, PER, motion={"per_sec": 4, "values": values})
        self.assertTrue(any(c["in"] <= 22 and c["out"] >= 48 for c in got[:2]))

    def test_a_talking_video_ignores_motion(self):
        cues = [(i * 6.0, i * 6.0 + 5.0, f"Line number {i} is said here.") for i in range(20)]
        calm = suggest.suggest(cues, 120, [], self.talking(), PER, motion={"per_sec": 4, "values": [0] * 480})
        wild = suggest.suggest(cues, 120, [], self.talking(), PER, motion={"per_sec": 4, "values": [255] * 480})
        self.assertEqual([(c["in"], c["out"], c["score"]) for c in calm], [(c["in"], c["out"], c["score"]) for c in wild])


if __name__ == "__main__":
    unittest.main()
