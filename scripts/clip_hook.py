"""The first seconds of a clip decide whether it is watched. Score the opening, and cut dead air before it."""
import re
from bisect import bisect_left

HOOK_SECS = 3.0
OPENER, START_ENERGY, CUT = 0.5, 0.35, 0.15
CUT_BEFORE, CUT_AFTER = 0.2, 1.0
DEAD_AIR = 1.0
ONSET_SHARE = 0.35
ONSET_FLOOR = 40
SOUND_FLOOR = 60
LEAD = 0.25

CONTINUES = re.compile(r"^\W*(and|but|so|because|which|then|also|or|that|anyway|yet|well|cause)\b(?!['’])", re.I)
QUESTION = re.compile(r"^\W*(what|why|how|who|where|when|did|do|does|is|are|can|could|would|wait|stop|look|no|don't|never|you)\b", re.I)
FIRST_SENTENCE = re.compile(r"^.*?[.!?…](?=\s|$)", re.S)


def opens_mid_thought(text):
    """True when the clip starts on a word that continues a sentence from before it."""
    return bool(CONTINUES.match(text))


def first_sentence(text):
    found = FIRST_SENTENCE.match(text.strip())
    return found.group(0) if found else text.strip()


def opener(text):
    """0 to 1 for how the first line grabs: a question or command, short, and not a continuation."""
    first = first_sentence(text)
    if opens_mid_thought(first):
        return 0.1
    score = 0.9 if first.rstrip().endswith(("?", "!")) or QUESTION.match(first) else 0.5
    count = len(first.split())
    return max(0.0, score - (0.3 if count > 20 else 0.1 if count > 12 else 0.0))


def start_energy(start, peaks, per_sec):
    """0 to 1 for how loud the opening seconds are, on their own and against the rest of the clip's neighbourhood."""
    lo = int(start * per_sec)
    window = peaks[lo:lo + int(HOOK_SECS * per_sec)]
    if not window:
        return 0.5
    mean = sum(window) / len(window) / 255
    around = peaks[lo:lo + int(30 * per_sec)]
    overall = sum(around) / len(around) / 255
    return 0.5 * min(1.0, mean / max(overall, 0.05) / 1.5) + 0.5 * mean


def cut_at_start(start, scenes):
    """1 when a scene cut lands on the opening, which reads as a deliberate start. `scenes` is sorted."""
    at = bisect_left(scenes, start - CUT_BEFORE)
    return 1.0 if at < len(scenes) and scenes[at] <= start + CUT_AFTER else 0.0


def hook(item, scenes, peaks, per_sec):
    """0 to 1 for how strong the first seconds of the clip are."""
    return min(1.0, max(0.0, OPENER * opener(item["text"])
                        + START_ENERGY * start_energy(item["in"], peaks, per_sec)
                        + CUT * cut_at_start(item["in"], scenes)))


def tighten(item, cues, peaks, per_sec, min_len=8.0):
    """A copy of the item starting where the sound starts, when the clip opens on dead air. A spoken line is never cut into."""
    lo = int(item["in"] * per_sec)
    window = peaks[lo:lo + int(HOOK_SECS * per_sec)]
    if not window or max(window) < SOUND_FLOOR:
        return item
    bar = max(ONSET_FLOOR, ONSET_SHARE * max(window))
    onset = next(i for i, p in enumerate(window) if p >= bar) / per_sec
    if onset < DEAD_AIR:
        return item
    start = item["in"] + onset - LEAD
    if item["out"] - start < min_len or any(a < start and b > item["in"] for a, b, _ in cues):
        return item
    return {**item, "in": round(start, 2)}


def better_start(item, cues, min_len=8.0):
    """The same clip starting at its next finished sentence, when it opens on a continuation. None when the opening is fine or too little would be left."""
    if not opens_mid_thought(first_sentence(item["text"])):
        return None
    inside = [i for i, (a, b, _) in enumerate(cues) if a >= item["in"] and b <= item["out"] + 0.01]
    for prev, i in zip(inside, inside[1:]):
        start, text = cues[i][0], cues[i][2]
        if not re.search(r"[.!?…][\"')\]]*$", cues[prev][2]) or opens_mid_thought(text):
            continue
        if item["out"] - start < min_len:
            return None
        return {**item, "in": round(max(0.0, start - LEAD), 2), "text": " ".join(cues[j][2] for j in inside if j >= i)}
    return None
