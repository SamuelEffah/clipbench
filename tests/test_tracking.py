import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import clipper
import make_short
import tracking


class SimplifyTests(unittest.TestCase):
    def walk(self, n=300, tremor=0.004):
        return [{"t": round(i * 0.1, 2), "x": round(0.4 + (tremor if i % 2 else -tremor), 4), "y": 0.3} for i in range(n)]

    def test_a_long_noisy_path_fits_the_keyframe_limit(self):
        self.assertLessEqual(len(tracking.simplify(self.walk())), tracking.MAX_KEYS)

    def test_tremor_is_dropped_so_a_steady_face_does_not_shake(self):
        self.assertLessEqual(len(tracking.simplify(self.walk())), 2)

    def test_a_real_move_and_a_jump_are_kept(self):
        path = [{"t": i * 0.1, "x": 0.3, "y": 0.3} for i in range(50)] + [{"t": 4.99 + i * 0.1 + 0.01, "x": 0.7, "y": 0.3} for i in range(50)]
        kept = tracking.simplify(path)
        self.assertEqual((kept[0]["x"], kept[-1]["x"]), (0.3, 0.7))
        self.assertTrue(any(a["x"] == 0.3 and b["x"] == 0.7 and b["t"] - a["t"] < 0.2 for a, b in zip(kept, kept[1:])))

    def test_a_path_that_wanders_still_fits_after_loosening(self):
        wander = [{"t": i * 0.1, "x": 0.5 + 0.3 * ((-1) ** (i // 3)) * (i % 3) / 3, "y": 0.3 + 0.002 * (i % 7)} for i in range(900)]
        self.assertLessEqual(len(tracking.simplify(wander)), tracking.MAX_KEYS)

    def test_short_paths_pass_through(self):
        short = [{"t": 0.0, "x": 0.2, "y": 0.3}, {"t": 1.0, "x": 0.8, "y": 0.4}]
        self.assertEqual(tracking.simplify(short), short)


class LongFollowTests(unittest.TestCase):
    def test_a_follow_track_longer_than_twelve_seconds_still_writes_a_cut_line(self):
        keys = [[10 + i * 0.1, 0.4 + (0.004 if i % 2 else -0.004), 0.3] for i in range(310)]
        line = clipper.track_line({"tracking": True, "in": 10, "track": keys}, 0)
        self.assertTrue(line.startswith("@track "))
        self.assertLessEqual(len(line[len("@track "):].split(",")), tracking.MAX_KEYS)


class TrackParsingTests(unittest.TestCase):
    def test_keyframes_parse_sorted_and_round_trip(self):
        keys = tracking.parse_track("2:0.6:0.3,0:0.2:0.3")
        self.assertEqual(keys, [(0.0, 0.2, 0.3), (2.0, 0.6, 0.3)])
        self.assertEqual(tracking.parse_track(tracking.format_track(keys)), keys)

    def test_bad_keyframes_are_refused(self):
        for bad in ("0:1.5:0.5", "x:0.5:0.5", "0:0.5", "-1:0.5:0.5"):
            with self.assertRaises(ValueError):
                tracking.parse_track(bad)
        with self.assertRaises(ValueError):
            tracking.parse_track(",".join(f"{i}:0.5:0.5" for i in range(tracking.MAX_KEYS + 1)))

    def test_cut_list_option_reaches_the_clip(self):
        (_, _, _, opts), = make_short.read_cuts("@zoom 2\n@track 0:0.1:0.5,2:0.9:0.5\n0:10 - 0:14")
        self.assertEqual(opts["track"], [(0.0, 0.1, 0.5), (2.0, 0.9, 0.5)])
        (_, _, _, plain), = make_short.read_cuts("0:10 - 0:14")
        self.assertIsNone(plain["track"])


class InterpolationTests(unittest.TestCase):
    keys = [(0.0, 0.2, 0.4), (2.0, 0.6, 0.4), (4.0, 0.6, 0.8)]

    def test_position_between_keyframes_is_a_straight_line(self):
        self.assertEqual(tracking.at(self.keys, 1.0), (0.4, 0.4))
        x, y = tracking.at(self.keys, 3.0)
        self.assertAlmostEqual(x, 0.6)
        self.assertAlmostEqual(y, 0.6)

    def test_it_holds_still_outside_the_keyframes(self):
        self.assertEqual(tracking.at(self.keys, -5), (0.2, 0.4))
        self.assertEqual(tracking.at(self.keys, 99), (0.6, 0.8))

    def test_ffmpeg_expression_names_every_keyframe_time(self):
        expr = tracking.expression(self.keys, 1)
        for t in ("2.000", "4.000"):
            self.assertIn(f"lt(t,{t})", expr)

    def test_retiming_follows_speed(self):
        keys = [(0.0, 0.2, 0.5), (4.0, 0.8, 0.5)]
        half = tracking.to_output_time(keys, 10.0, [(10.0, 14.0, 2.0)])
        self.assertEqual([k[0] for k in half], [0.0, 2.0])
        ramp = tracking.to_output_time(keys, 10.0, [(10.0, 12.0, 1.0), (12.0, 14.0, 2.0)])
        self.assertEqual([k[0] for k in ramp], [0.0, 3.0])


class SmoothingTests(unittest.TestCase):
    def test_a_stray_hit_does_not_move_the_track(self):
        samples = [{"t": t, "x": 0.5, "y": 0.5} for t in range(7)]
        samples[3] = {"t": 3, "x": 0.95, "y": 0.05}
        out = tracking.smooth(samples)
        self.assertTrue(all(abs(s["x"] - 0.5) < 0.01 and abs(s["y"] - 0.5) < 0.01 for s in out))

    def test_the_crop_cannot_move_faster_than_the_cap(self):
        samples = [{"t": 0, "x": 0.1, "y": 0.5}, {"t": 1, "x": 0.9, "y": 0.5}, {"t": 2, "x": 0.9, "y": 0.5}, {"t": 3, "x": 0.9, "y": 0.5}]
        out = tracking.smooth(samples, window=1)
        steps = [abs(b["x"] - a["x"]) for a, b in zip(out, out[1:])]
        self.assertTrue(all(s <= tracking.MAX_SPEED + 1e-6 for s in steps))


class RenderTests(unittest.TestCase):
    opts = {**make_short.DEFAULT_OPTIONS, "zoom": 2.0, "fit": "fill"}

    def test_a_clip_without_a_track_renders_exactly_as_before(self):
        self.assertIn("crop=iw/2.0000:ih/2.0000:(iw-ow)*0.500:(ih-oh)*0.500,", make_short.zoom_filter(1080, 1920, self.opts))

    def test_a_track_moves_the_crop_with_time(self):
        f = make_short.zoom_filter(1080, 1920, self.opts, [(0.0, 0.1, 0.5), (2.0, 0.9, 0.5)])
        self.assertIn("lt(t,2.000)", f)

    def test_a_track_is_ignored_without_zoom(self):
        self.assertEqual(make_short.zoom_filter(1080, 1920, {**self.opts, "zoom": 1.0}, [(0.0, 0.1, 0.5)]), "")


class ExportTests(unittest.TestCase):
    clip = {"in": 10.0, "out": 14.0, "tracking": True, "track": [[10.0, 0.2, 0.5], [12.0, 0.7, 0.5]]}

    def test_the_line_uses_seconds_into_the_clip(self):
        self.assertEqual(clipper.track_line(self.clip, 0), "@track 0.00:0.200:0.500,2.00:0.700:0.500")

    def test_off_or_empty_writes_nothing(self):
        self.assertEqual(clipper.track_line({**self.clip, "tracking": False}, 0), "")
        self.assertEqual(clipper.track_line({**self.clip, "track": []}, 0), "")

    def test_a_bad_path_is_named_by_clip(self):
        with self.assertRaises(ValueError):
            clipper.track_line({**self.clip, "track": [[10, 2.0, 0.5]]}, 3)


if __name__ == "__main__":
    unittest.main()
