"""Pauses in talk: the quiet stretches between what is said, measured against the clip's own speech level. A fixed
threshold misses them, since an interview sits on a bed of room tone and music, so the floor and the speech level are
read from the clip and a pause is what drops well below the speech. Each pause is returned a little shorter than the
quiet itself, so a cut on it leaves a breath and clips no consonant."""
import re
import subprocess

STEP = 0.05  # seconds per loudness frame
MIN_PAUSE = 0.35  # a quieter run shorter than this is the gap between two words
MARGIN = 0.1  # kept at each end of a pause so the cut lands on silence
MIN_CUT = 0.2  # a pause not worth cutting once the margins are kept
SPEECH_OVER_FLOOR = 8  # dB; with less contrast the sound is a steady bed, with no pauses to find
BELOW_SPEECH = 12  # dB under the speech level that counts as quiet
ABOVE_FLOOR = 4  # dB; quiet is also never far above the floor
BLIP = 1  # frames louder than the threshold a pause may hold, such as a click or a breath

LEVEL = re.compile(r"pts_time:([\d.]+)\s*\n[^\n]*RMS_level=(-?[\d.]+|-inf)")


def percentile(sorted_values, share):
    return sorted_values[min(len(sorted_values) - 1, int(len(sorted_values) * share))]


def quiet_runs(levels, threshold, step):
    """Stretches (start, end) where the level stays at or under the threshold, allowing BLIP louder frames inside."""
    runs, start, loud = [], None, 0
    for t, level in levels:
        if level <= threshold:
            start, loud = t if start is None else start, 0
        elif start is not None and loud < BLIP:
            loud += 1
        elif start is not None:
            runs.append((start, t - loud * step))
            start, loud = None, 0
    if start is not None:
        runs.append((start, levels[-1][0] + step - loud * step))
    return runs


def find_pauses(levels, step=STEP):
    """Pauses [[start, end]] to cut from loudness frames (time, dB), each frame covering `step` seconds from its time."""
    if len(levels) < 2:
        return []
    ordered = sorted(level for _, level in levels)
    floor, speech = percentile(ordered, 0.1), percentile(ordered, 0.8)
    if speech - floor < SPEECH_OVER_FLOOR:
        return []
    threshold = max(floor + ABOVE_FLOOR, speech - BELOW_SPEECH)
    cuts = [[round(a + MARGIN, 2), round(b - MARGIN, 2)] for a, b in quiet_runs(levels, threshold, step) if b - a >= MIN_PAUSE]
    return [c for c in cuts if c[1] - c[0] >= MIN_CUT]


def levels(src, start, end, step=STEP):
    """Loudness frames (time, dB) of the sound between start and end, times in the video's own seconds."""
    done = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", src, "-ac", "1", "-af",
         f"astats=metadata=1:reset=1:length={step},ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-", "-f", "null", "-"],
        capture_output=True, text=True)
    if done.returncode != 0:
        raise OSError(done.stderr.strip()[-300:] or "could not read the sound")
    return [(round(start + float(t), 3), -99.0 if v == "-inf" else float(v)) for t, v in LEVEL.findall(done.stdout)]


def pauses(src, start, end):
    return {"pauses": find_pauses(levels(src, start, end))}
