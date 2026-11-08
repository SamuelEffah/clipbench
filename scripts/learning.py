"""Learn from what happened to earlier suggestions: which were kept or skipped, and how the Shorts cut from them did on YouTube.

A moment is described by a few coarse features (its label, whether each part of its score was high or low, the kind of
video). Every past decision and every published Short gives its moment a value; a new suggestion sharing those features
moves up or down by their average, gently while the evidence is thin.
"""
import re
from statistics import median

KEEP_VALUE = 0.5  # a kept suggestion
SKIP_VALUE = -1.0  # a skipped one
OUTCOME_MAX = 1.5  # the most a published Short can be worth
HIGH = 60  # a part of the score at or above this, out of 100, counts as high
PRIOR = 5  # examples a feature needs before its lesson counts about half
LEARN_WEIGHT = 0.3  # how much of a score the lessons can move at most, per unit of value
VIEWS_CAP = 1.5  # views beyond this many times the typical count no longer add
WATCH_MIDDLE = 60.0  # percent watched that counts as neither good nor bad
WATCH_SPAN = 40.0
OVERLAP_SHARE = 0.5  # how much of a clip a suggestion has to cover to be where it came from
HOLD_GAIN = 5.0  # how strongly a stretch keeping more or fewer viewers than its share of the Short counts
HOLD_WEIGHT = 0.5  # how much a stretch's hold shifts the Short's value for the moment cut there
OPENING = 3.0  # seconds at the start of a clip that are its opening
PARTS = ("hook", "energy", "words", "motion")
LABELS = {"why:joke": "jokes", "why:shock": "shocks", "why:emotion": "emotional moments", "why:cliffhanger": "cliffhangers",
          "why:reveal": "reveals", "why:action": "action", "why:explanation": "explanations",
          "hook:high": "strong openings", "hook:low": "slow openings", "energy:high": "loud moments", "energy:low": "quiet moments",
          "words:high": "punchy lines", "words:low": "plain lines", "motion:high": "busy pictures", "motion:low": "still pictures"}
KINDS = {"speech": "talk videos", "audio": "quiet videos", "visual": "fast-cut videos", "mixed": "mixed videos"}
SPACES = re.compile(r"\s+")
HASHTAGS = re.compile(r"#\w+")
STEM_MIN = 12  # characters a title needs, without its hashtags, before it can match a video on the channel


def features(moment):
    """The coarse description of a moment: its label, each measured part as high or low, the kind of video, and the
    label together with the kind, so what works in one kind of video is learned apart from the others."""
    if not isinstance(moment, dict):
        return set()
    found = set()
    why = moment.get("why")
    profile = moment.get("profile")
    if isinstance(why, str) and why:
        found.add(f"why:{why.lower()}")
        if isinstance(profile, str) and profile:
            found.add(f"why:{why.lower()}@{profile}")
    parts = moment.get("parts") if isinstance(moment.get("parts"), dict) else {}
    for part in PARTS:
        value = parts.get(part)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            found.add(f"{part}:{'high' if value >= HIGH else 'low'}")
    if isinstance(profile, str) and profile:
        found.add(f"profile:{profile}")
    return found


def label_of(feature):
    """The words for a feature in a note, or None for one that has none."""
    if feature in LABELS:
        return LABELS[feature]
    plain, _, kind = feature.partition("@")
    if kind and plain in LABELS and kind in KINDS:
        return f"{LABELS[plain]} in {KINDS[kind]}"
    return None


def typical_views(stats):
    """The median views of the videos still up, or None when there are none."""
    counts = [row.get("views") or 0 for row in stats.values() if not row.get("gone")]
    return median(counts) if counts else None


def outcome(row, typical):
    """How well a published Short did, -1 to OUTCOME_MAX, from its views against the typical count and how much of it
    was watched. None for a video that is gone or when nothing is typical yet."""
    if not row or row.get("gone") or not typical:
        return None
    parts = [min(VIEWS_CAP, (row.get("views") or 0) / typical) - 0.5]
    watched = row.get("avg_percent")
    if isinstance(watched, (int, float)):
        parts.append(max(-1.0, min(1.0, (watched - WATCH_MIDDLE) / WATCH_SPAN)))
    return max(-1.0, min(OUTCOME_MAX, sum(parts) / len(parts)))


def lessons(examples):
    """{feature: (mean value, how many examples had it)} from [(moment, value)]."""
    totals = {}
    for moment, value in examples:
        for feature in features(moment):
            total, count = totals.get(feature, (0.0, 0))
            totals[feature] = (total + value, count + 1)
    return {feature: (total / count, count) for feature, (total, count) in totals.items()}


def review_examples(reviews):
    """Kept and skipped suggestions as examples; a review whose moment says nothing is left out."""
    values = {"keep": KEEP_VALUE, "skip": SKIP_VALUE}
    return [(r["moment"], values[r["decision"]]) for r in reviews if r.get("decision") in values and features(r.get("moment"))]


def _weight(lesson):
    mean, count = lesson
    return mean * count / (count + PRIOR)


def _note(found, known, change):
    """One line naming the feature that pushed the score the way it went, the label of the moment before any part of
    its score. Nothing when no named feature pushed that way."""
    named = [(f, _weight(known[f])) for f in found if f in known and label_of(f)]
    agreeing = [(f, w) for f, w in named if (w > 0) == (change > 0) and w]
    if not agreeing:
        return ""
    feature, weight = max(agreeing, key=lambda fw: (abs(fw[1]), fw[0].startswith("why:"), "@" not in fw[0]))
    return f"{label_of(feature)} {'did well' if weight > 0 else 'did poorly'} before"


def adjust(items, known, profile=None):
    """The items re-scored by what their features did before, best first. Items whose features taught nothing are
    returned as they are; the rest carry `learned` with the change in percent and a one-line reason. `profile` is the
    kind of video the items come from, when they do not carry it themselves."""
    out = []
    for it in items:
        found = features({**it, "profile": profile} if profile and isinstance(it, dict) else it)
        weights = [_weight(known[f]) for f in found if f in known]
        if not weights:
            out.append(it)
            continue
        change = LEARN_WEIGHT * sum(weights) / len(weights)
        out.append({**it, "score": round(it["score"] * (1 + change), 3), "learned": {"delta": round(change * 100), "note": _note(found, known, change)}})
    return sorted(_without_uniform_notes(out), key=lambda it: -it["score"])


def _without_uniform_notes(items):
    """The items minus their notes when every one of them moved by the same amount: a list that all went the same way
    says nothing about which to pick, so the notes would only be noise."""
    deltas = {it["learned"]["delta"] for it in items if isinstance(it, dict) and "learned" in it}
    if len(items) < 2 or len(deltas) != 1 or any("learned" not in it for it in items):
        return items
    return [{k: v for k, v in it.items() if k != "learned"} for it in items]


def _stem(title):
    """A title without its hashtags, spacing or case, to match the title file against what the video was called on YouTube."""
    return SPACES.sub(" ", HASHTAGS.sub(" ", str(title or ""))).strip().casefold()


def _same_title(a, b):
    """Two stems name the same Short when one is the other, or the other with something added after it."""
    return len(a) >= STEM_MIN and len(b) >= STEM_MIN and (a.startswith(b) or b.startswith(a))


def published(shorts, channel_videos):
    """{Short name: YouTube video id} for every rendered Short that was uploaded by the app, or posted by hand under the
    title in its title file, allowing for hashtags or a tail added on YouTube."""
    titled = [(_stem(v.get("title")), v["video_id"]) for v in channel_videos]
    found = {}
    for short in shorts:
        upload = short.get("upload") or {}
        stem = _stem(short.get("title"))
        if upload.get("state") == "done" and upload.get("video_id"):
            found[short["name"]] = upload["video_id"]
        elif match := next((vid for other, vid in titled if _same_title(stem, other)), None):
            found[short["name"]] = match
    return found


def moment_of(clip, suggestions):
    """The suggestion a clip was cut from: the one covering most of it, at least OVERLAP_SHARE of its length. None otherwise."""
    start, end = float(clip["in"]), float(clip["out"])
    best, most = None, (end - start) * OVERLAP_SHARE
    for s in suggestions:
        overlap = min(end, float(s["out"])) - max(start, float(s["in"]))
        if overlap >= most and overlap > 0:
            best, most = s, overlap
    return best


def _same_clip(a, b):
    try:
        return a.get("src") == b.get("src") and abs(float(a["in"]) - float(b["in"])) < 0.01 and abs(float(a["out"]) - float(b["out"])) < 0.01
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def measured_moment(clip, snapshot):
    """The moment measured for a clip when its Short was rendered, from the snapshot's `moments`, or None."""
    return next((m for m in snapshot.get("moments") or [] if isinstance(m, dict) and _same_clip(m, clip)), None)


def _number(value, default):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else default


def clip_lengths(clips):
    """Seconds each clip lasts in the Short: its source stretch at its speed, plus any held last frame."""
    return [(float(c["out"]) - float(c["in"])) / _number(c.get("speed"), 1.0) + max(0.0, _number(c.get("freeze"), 0.0)) for c in clips]


def watched_at(curve, fraction):
    """The share of viewers still watching this far along the Short, from its retention curve of evenly spaced points."""
    return float(curve[max(0, min(len(curve) - 1, int(fraction * len(curve))))])


def hold_value(curve, start, end, total):
    """-1 to 1: how the stretch from `start` to `end` seconds of a `total`-second Short held its viewers, against the hold
    the whole Short would show over the same share of its length were viewers lost evenly along it. None without a
    usable curve."""
    if not curve or not total or total <= 0 or end <= start:
        return None
    try:
        first, last = watched_at(curve, 0.0), watched_at(curve, 1.0)
        at_start, at_end = watched_at(curve, start / total), watched_at(curve, end / total)
    except (TypeError, ValueError):
        return None
    if first <= 0 or last <= 0 or at_start <= 0:
        return None
    par = (last / first) ** ((end - start) / total)
    return max(-1.0, min(1.0, HOLD_GAIN * (at_end / at_start / par - 1)))


def stretch_examples(moment, value, curve, start, end, total):
    """The examples one clip of a published Short gives: its moment at the Short's value shifted by how the clip held
    viewers, and, when the moment has a hook score, the hook alone shifted by how the clip's opening held them."""
    held = hold_value(curve, start, end, total)
    if held is None:
        return [(moment, value)]
    examples = [(moment, _shifted(value, held))]
    hook = (moment.get("parts") or {}).get("hook") if isinstance(moment.get("parts"), dict) else None
    opening = hold_value(curve, start, min(end, start + OPENING), total)
    if isinstance(hook, (int, float)) and not isinstance(hook, bool) and opening is not None:
        examples.append(({"parts": {"hook": hook}}, _shifted(value, opening)))
    return examples


def _shifted(value, held):
    return max(-1.0, min(OUTCOME_MAX, value + HOLD_WEIGHT * held))


def _top_clips(snapshot):
    return [c for c in (snapshot or {}).get("clips") or []
            if isinstance(c, dict) and c.get("lane", "top") == "top" and "in" in c and "out" in c]


def published_examples(shorts_to_videos, stats, snapshot_of, suggestions_of):
    """[(moment, value)] for every published Short with figures: each top-lane clip of the project as it was rendered
    (`snapshot_of(name)`) is traced to the suggestion it was cut from among `suggestions_of(src)`, or failing that to
    the moment measured for it at render time. With a retention curve, each clip is judged by where along the Short
    its viewers left."""
    typical = typical_views(stats)
    examples, seen = [], set()
    for name, video_id in shorts_to_videos.items():
        row = stats.get(video_id) or {}
        value = outcome(row, typical)
        if value is None:
            continue
        clips = _top_clips(snapshot := snapshot_of(name))
        try:
            lengths = clip_lengths(clips)
        except (TypeError, ValueError):
            continue
        total, at = sum(lengths), 0.0
        curve = row.get("retention") if isinstance(row.get("retention"), list) else None
        for clip, length in zip(clips, lengths):
            start, at = at, at + length
            moment = moment_of(clip, suggestions_of(clip.get("src"))) or measured_moment(clip, snapshot)
            key = (name, clip.get("src"), moment and moment.get("in"), moment and moment.get("out"))
            if moment and key not in seen:
                seen.add(key)
                examples += stretch_examples(moment, value, curve, start, at, total)
    return examples
