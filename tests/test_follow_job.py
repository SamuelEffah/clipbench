import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import clipper  # noqa: E402

BOX = {"x": 0.2, "y": 0.2, "w": 0.1, "h": 0.3}
SAMPLES = [{"t": 0.0, "x": 0.25, "y": 0.35}, {"t": 0.5, "x": 0.3, "y": 0.35}]


def run(job, person=None, subject=None):
    with mock.patch.object(clipper, "followed_people", return_value=person) as people, \
            mock.patch.object(clipper.reframe, "follow_subject", return_value=subject) as old, \
            mock.patch.object(clipper.reframe, "probe_size", return_value=(1920, 1080)):
        clipper.run_follow(job, "/v.mp4", 0.0, 5.0, BOX, 0.0)
    return people, old


class FollowJob(unittest.TestCase):
    def test_a_person_is_followed_with_the_detector_and_the_job_finishes(self):
        job = {"state": "queued", "pct": 0}
        people, old = run(job, person={"samples": SAMPLES})
        self.assertEqual(job["state"], "ready")
        self.assertEqual((job["width"], job["height"]), (1920, 1080))
        self.assertEqual(len(job["track"]), 2)
        old.assert_not_called()

    def test_without_a_person_the_older_tracker_takes_over(self):
        job = {"state": "queued", "pct": 0}
        people, old = run(job, person=None, subject={"samples": SAMPLES})
        self.assertEqual(job["state"], "ready")
        old.assert_called_once()

    def test_a_failure_becomes_a_message_not_a_crash(self):
        job = {"state": "queued", "pct": 0}
        with mock.patch.object(clipper, "followed_people", side_effect=ValueError("Pick a clip under 180 seconds")):
            clipper.run_follow(job, "/v.mp4", 0.0, 500.0, BOX, 0.0)
        self.assertEqual(job["state"], "error")
        self.assertIn("180", job["message"])

    def test_progress_from_the_detector_reaches_the_job(self):
        job = {"state": "queued", "pct": 0}

        def fake(src, start, end, box, at, progress=None):
            progress(3, 4)
            self.assertEqual(job["state"], "working")
            self.assertEqual(job["pct"], 75)
            return {"samples": SAMPLES}
        with mock.patch.object(clipper, "followed_people", side_effect=fake), \
                mock.patch.object(clipper.reframe, "probe_size", return_value=(1920, 1080)):
            clipper.run_follow(job, "/v.mp4", 0.0, 5.0, BOX, 0.0)
        self.assertEqual(job["state"], "ready")

    def test_old_finished_jobs_are_dropped(self):
        clipper.follow_jobs.clear()
        with mock.patch.object(clipper, "run_follow"):
            ids = [clipper.start_follow("/v.mp4", 0, 1, BOX, 0)["id"] for _ in range(clipper.FOLLOW_JOBS_KEPT + 5)]
            for i in ids:
                clipper.follow_jobs[i]["state"] = "ready"
            clipper.start_follow("/v.mp4", 0, 1, BOX, 0)
        self.assertLessEqual(len(clipper.follow_jobs), clipper.FOLLOW_JOBS_KEPT + 1)
        self.assertNotIn(ids[0], clipper.follow_jobs)


if __name__ == "__main__":
    unittest.main()
