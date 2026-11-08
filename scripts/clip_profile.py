"""What kind of media a video is, so clip scoring can lean on the signals that carry it.

A podcast lives in its words, a montage in its cuts, a concert in its sound. The profile is measured
from the lines said, the scene cuts and the length alone, so it needs no genre list."""

SPEECH_LED = 0.5
LITTLE_SPEECH = 0.25
VISUAL_CUTS = 6.0
# Music and engine noise play on without the gaps that talk has: little of the track is quiet, and the level hardly swings.
STEADY_QUIET = 0.08
STEADY_SWING = 0.45
QUIET_BELOW = 0.2

KINDS = ("speech", "visual", "audio", "mixed")
WEIGHTS = {
    "speech": {"energy": 0.6, "wording": 1.0, "hook": 0.25, "motion": 0.0},
    "visual": {"energy": 1.0, "wording": 0.3, "hook": 0.3, "motion": 1.0},
    "audio": {"energy": 1.0, "wording": 0.4, "hook": 0.3, "motion": 0.4},
    "mixed": {"energy": 0.8, "wording": 0.8, "hook": 0.25, "motion": 0.4},
}


def steady_sound(peaks):
    """True when the sound runs on without pauses, as music does, and not in bursts as talk does."""
    if len(peaks) < 100:
        return False
    top = sorted(peaks)[int(0.9 * len(peaks))]
    if top <= 0:
        return False
    mean = sum(peaks) / len(peaks)
    swing = (sum((v - mean) ** 2 for v in peaks) / len(peaks)) ** 0.5 / (mean or 1)
    quiet = sum(v < QUIET_BELOW * top for v in peaks) / len(peaks)
    return quiet < STEADY_QUIET and swing < STEADY_SWING


def profile(cues, duration, scenes, peaks, per_sec):
    """{kind, speech, cuts, pace, steady}: how much of the video is talk (0 to 1), cuts per minute, words per spoken
    minute, and whether the sound runs on without pauses. Sound like that is not talk, so whatever was heard in it
    (sung words) does not make the video a talking one."""
    if duration <= 0:
        return {"kind": "audio", "speech": 0, "cuts": 0, "pace": 0, "steady": False}
    spoken = sum(max(0.0, stop - start) for start, stop, _ in cues)
    words = sum(len(text.split()) for _, _, text in cues)
    speech = min(1.0, spoken / duration)
    cuts = len(scenes) / (duration / 60)
    pace = words / (spoken / 60) if spoken else 0
    steady = steady_sound(peaks)
    if steady:
        kind = "visual" if cuts >= VISUAL_CUTS else "audio"
    elif speech >= SPEECH_LED:
        kind = "speech"
    elif speech < LITTLE_SPEECH:
        kind = "visual" if cuts >= VISUAL_CUTS else "audio"
    else:
        kind = "mixed"
    return {"kind": kind, "speech": round(speech, 3), "cuts": round(cuts, 2), "pace": round(pace), "steady": steady}


def weights(found):
    """How much each signal counts for a video of this profile."""
    return WEIGHTS.get(found.get("kind"), WEIGHTS["mixed"])
