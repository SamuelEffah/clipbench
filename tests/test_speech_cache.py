import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts import speech_cache  # noqa: E402

WORDS = [["hello", 1.6, 2.0], ["there", 2.0, 2.6], ["friend", 5.0, 5.5]]


class SpeechCacheTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.heard = []

    def cache(self, words=WORDS):
        def listen(src, a, b):
            self.heard.append((src, a, b))
            return words
        return speech_cache.SpeechCache(self.dir.name, listen)

    def test_a_clip_is_listened_to_a_little_wider_than_itself(self):
        cache = self.cache()
        cache.queue("v.mp4", 10.0, 20.0)
        self.assertTrue(cache.wait())
        self.assertEqual(self.heard, [("v.mp4", 8.5, 21.5)])

    def test_words_come_back_timed_from_the_start_of_the_clip(self):
        cache = self.cache()
        cache.queue("v.mp4", 10.0, 20.0)
        cache.wait()
        self.assertEqual(cache.find("v.mp4", 10.0, 20.0), [["hello", 0.1, 0.5], ["there", 0.5, 1.1], ["friend", 3.5, 4.0]])

    def test_a_trimmed_clip_reuses_the_same_listen(self):
        cache = self.cache()
        cache.queue("v.mp4", 10.0, 20.0)
        cache.wait()
        trimmed = cache.find("v.mp4", 9.0, 19.5)
        self.assertEqual(trimmed[-1], ["friend", 4.5, 5.0])
        cache.queue("v.mp4", 9.0, 19.5)
        cache.wait()
        self.assertEqual(len(self.heard), 1)

    def test_a_word_cut_in_half_by_the_clip_edge_belongs_to_the_clip_it_mostly_sits_in(self):
        cache = self.cache([["lose", 1.2, 1.6], ["today", 1.8, 2.2]])
        cache.queue("v.mp4", 10.0, 20.0)
        cache.wait()
        self.assertEqual([w[0] for w in cache.find("v.mp4", 10.0, 20.0)], ["today"])

    def test_a_clip_that_reaches_past_what_was_heard_is_listened_to_again(self):
        cache = self.cache()
        cache.queue("v.mp4", 10.0, 20.0)
        cache.wait()
        self.assertIsNone(cache.find("v.mp4", 5.0, 20.0))

    def test_a_clip_with_no_speech_is_remembered_as_empty(self):
        cache = self.cache([])
        cache.queue("v.mp4", 10.0, 20.0)
        cache.wait()
        self.assertEqual(cache.find("v.mp4", 10.0, 20.0), [])

    def test_a_failed_listen_is_not_remembered(self):
        cache = speech_cache.SpeechCache(self.dir.name, lambda *args: None)
        cache.queue("v.mp4", 10.0, 20.0)
        cache.wait()
        self.assertIsNone(cache.find("v.mp4", 10.0, 20.0))

    def test_what_was_heard_survives_a_restart(self):
        first = self.cache()
        first.queue("v.mp4", 10.0, 20.0)
        first.wait()
        again = speech_cache.SpeechCache(self.dir.name, lambda *args: None)
        self.assertEqual(again.find("v.mp4", 10.0, 20.0), first.find("v.mp4", 10.0, 20.0))

    def test_the_same_clip_is_not_queued_twice(self):
        cache = self.cache()
        self.assertTrue(cache.queue("v.mp4", 10.0, 20.0))
        cache.wait()
        self.assertFalse(cache.queue("v.mp4", 10.0, 20.0))


if __name__ == "__main__":
    unittest.main()
