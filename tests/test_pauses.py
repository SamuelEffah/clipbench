import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pauses  # noqa: E402
from scripts import clipper  # noqa: E402

STEP = 0.05


def track(*parts):
    """Levels in dB as (time, level) frames: each part is (seconds, level)."""
    out, t = [], 0.0
    for seconds, level in parts:
        for _ in range(round(seconds / STEP)):
            out.append((round(t, 3), level))
            t += STEP
    return out


class FindingPauses(unittest.TestCase):
    def test_a_quiet_stretch_between_speech_is_a_pause_with_a_margin_kept_on_each_side(self):
        levels = track((3, -15), (1, -35), (3, -14))
        self.assertEqual(pauses.find_pauses(levels, STEP), [[3.1, 3.9]])

    def test_a_breath_between_words_is_not_a_pause(self):
        levels = track((3, -15), (0.2, -35), (3, -14))
        self.assertEqual(pauses.find_pauses(levels, STEP), [])

    def test_a_steady_bed_of_sound_has_no_pauses_to_cut(self):
        levels = track((3, -15), (1, -19), (3, -14))
        self.assertEqual(pauses.find_pauses(levels, STEP), [])

    def test_the_threshold_follows_the_speech_so_a_loud_room_still_shows_its_pauses(self):
        levels = track((3, -8), (1, -24), (3, -9), (0.6, -23), (3, -8))
        self.assertEqual(pauses.find_pauses(levels, STEP), [[3.1, 3.9], [7.1, 7.5]])

    def test_a_single_louder_frame_inside_a_pause_does_not_split_it(self):
        levels = track((3, -15), (0.5, -35), (STEP, -22), (0.5, -35), (3, -14))
        self.assertEqual(pauses.find_pauses(levels, STEP), [[3.1, 3.95]])

    def test_times_are_measured_from_where_the_levels_start(self):
        levels = [(t + 120.0, v) for t, v in track((3, -15), (1, -35), (3, -14))]
        self.assertEqual(pauses.find_pauses(levels, STEP), [[123.1, 123.9]])

    def test_too_little_sound_to_judge_gives_nothing(self):
        self.assertEqual(pauses.find_pauses([], STEP), [])
        self.assertEqual(pauses.find_pauses([(0, -15)], STEP), [])


class PausesRoute(unittest.TestCase):
    def post(self, body):
        handler = object.__new__(clipper.Handler)
        handler.host_ok = handler.origin_ok = lambda: True
        handler.path = "/api/pauses"
        handler.read_json = lambda: body
        result = []
        handler.send_json = lambda data, status=200: result.append((data, status))
        handler.do_POST()
        return result

    def test_pauses_of_a_known_video_come_back(self):
        with mock.patch.object(clipper, "registry", {"abc": Path("/v/talk.mp4")}), \
             mock.patch.object(clipper.pauses, "pauses", return_value={"pauses": [[12.1, 12.9]]}) as found:
            result = self.post({"src": "/v/talk.mp4", "in": 10, "out": 50})
        self.assertEqual(result, [({"pauses": [[12.1, 12.9]]}, 200)])
        found.assert_called_once_with("/v/talk.mp4", 10.0, 50.0)

    def test_a_bad_range_or_unknown_video_is_refused(self):
        with mock.patch.object(clipper, "registry", {"abc": Path("/v/talk.mp4")}):
            self.assertEqual(self.post({"src": "/v/talk.mp4", "in": "x", "out": 50})[0][1], 400)
            self.assertEqual(self.post({"src": "/v/other.mp4", "in": 10, "out": 50})[0][1], 400)
            self.assertEqual(self.post({"src": "/v/talk.mp4", "in": 50, "out": 10})[0][1], 400)

    def test_a_video_that_cannot_be_read_is_reported(self):
        with mock.patch.object(clipper, "registry", {"abc": Path("/v/talk.mp4")}), \
             mock.patch.object(clipper.pauses, "pauses", side_effect=OSError("no such file")):
            result = self.post({"src": "/v/talk.mp4", "in": 10, "out": 50})
        self.assertEqual(result[0][1], 400)
        self.assertIn("no such file", result[0][0]["error"])


if __name__ == "__main__":
    unittest.main()
