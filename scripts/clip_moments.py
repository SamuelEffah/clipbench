"""Candidate clips found from the sound and the cuts alone, for video where little is said.

Without words there are no sentences to cut at, so slide windows along the loudness track, keep the
strongest, and move their edges onto nearby scene cuts."""
from bisect import bisect_left

MIN_LEN = 8.0
MAX_LEN = 40.0
LENGTHS = (12.0, 20.0, 30.0, MAX_LEN)
STEP = 2.0
KEEP = 40
MAX_OVERLAP = 0.6
SNAP = 1.5
SPREAD_SHARE = 0.25
# A stretch that is only active in part is worth this much less per missing share, so a lone spike cannot carry a long window.
SUSTAIN_WEIGHT = 0.6
SHOT_BONUS = 0.1
# A longer window that holds an already picked one takes its place when it is nearly as strong (within this share of its rating).
GROW_TOLERANCE = 0.08


def _snap(time, cuts):
    at = bisect_left(cuts, time)
    near = [cuts[i] for i in (at - 1, at) if 0 <= i < len(cuts) and abs(cuts[i] - time) <= SNAP]
    return min(near, key=lambda c: abs(c - time)) if near else time


def _edge(time, cuts, beats):
    cut = _snap(time, cuts)
    return cut if cut != time or not beats else _snap(time, beats)


def strength(peaks, per_sec, start, end):
    """0 to 1 for how loud the stretch is: its average plus some of how far its loudest moment stands above that,
    scaled down by how much of the stretch is quiet next to that loudest moment."""
    seg = peaks[int(start * per_sec):int(end * per_sec)]
    if not seg:
        return 0.0
    mean = sum(seg) / len(seg)
    top = max(seg)
    active = sum(v >= top / 2 for v in seg) / len(seg)
    return (mean + SPREAD_SHARE * (top - mean)) / 255 * (1 - SUSTAIN_WEIGHT + SUSTAIN_WEIGHT * active)


def level(peaks, per_sec, start, end, motion=None, motion_weight=0.0):
    """0 to 1 for how strong the stretch is: its sound, blended with how much the picture moves when that counts."""
    sound = strength(peaks, per_sec, start, end)
    if not motion or not motion.get("values") or motion_weight <= 0:
        return sound
    moving = strength(motion["values"], motion["per_sec"], start, end)
    return (sound + motion_weight * moving) / (1 + motion_weight)


def _overlap(a, b):
    shared = min(a["out"], b["out"]) - max(a["in"], b["in"])
    return max(0.0, shared) / min(a["out"] - a["in"], b["out"] - b["in"])


def windows(duration, scenes, peaks, per_sec, cues=(), motion=None, motion_weight=0.0, beats=()):
    """Loud stretches of the video as {in, out, text}, strongest first. `text` is what was said inside, if anything.
    Edges go to a scene cut when one is near, and otherwise to a beat in `beats`."""
    if duration < MIN_LEN or not peaks:
        return []
    cuts = sorted(scenes)
    hits = sorted(beats)
    lengths = [n for n in LENGTHS if n <= duration] or [duration]
    scored = []
    for length in lengths:
        start = 0.0
        while start + length <= duration + 1e-6:
            scored.append((start, start + length, 0.0))
            start += STEP
    # A shot between two cuts is a natural clip when it is a sensible length.
    shots = [0.0] + cuts + [duration]
    scored += [(a, b, SHOT_BONUS) for a, b in zip(shots, shots[1:]) if MIN_LEN <= b - a <= MAX_LEN]
    kept = []
    rated = [(round(level(peaks, per_sec, a, b, motion, motion_weight) + bonus, 2), a, b) for a, b, bonus in scored]
    # Equal strength goes to the longer window, so a loud stretch is offered whole rather than as a sample of it.
    for rate, a, b in sorted(rated, key=lambda r: (-r[0], -(r[2] - r[1]))):
        a, b = max(0.0, _edge(a, cuts, hits)), min(duration, _edge(b, cuts, hits))
        if not MIN_LEN <= b - a <= MAX_LEN + 2:
            continue
        found = {"in": round(a, 2), "out": round(b, 2)}
        said = [t for s, e, t in cues if s >= a - 0.01 and e <= b + 0.01]
        clip = {**found, "text": " ".join(said), "before": "", "after": "", "silent": not said}
        inside = [i for i, (k, r) in enumerate(kept) if found["in"] <= k["in"] and k["out"] <= found["out"] and rate >= r * (1 - GROW_TOLERANCE)]
        if inside:
            keep_at = inside[0]
            rest = [kr for i, kr in enumerate(kept) if i not in inside]
            if not any(_overlap(found, k) > MAX_OVERLAP for k, _ in rest):
                best = max(r for i, (_, r) in enumerate(kept) if i in inside)
                kept = rest[:keep_at] + [(clip, best)] + rest[keep_at:]
                continue
        if any(_overlap(found, k) > MAX_OVERLAP for k, _ in kept):
            continue
        kept.append((clip, rate))
        if len(kept) == KEEP:
            break
    return [k for k, _ in kept]
