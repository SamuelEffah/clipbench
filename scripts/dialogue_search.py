"""Search what is said across every video that has English subtitles, and frame each hit as a clip that starts and ends on a scene cut."""
import re

import suggest

MIN_QUERY = 2
MAX_RESULTS = 40
SPLIT_GAP = 1.5
LEAD = 0.3
TAIL = 0.5
SNAP_BEFORE = 1.0
SNAP_AFTER = 1.0
MIN_LEN = 1.5
NOISE = re.compile(r"[^\w\s]|_")


def normalize(text):
    return " ".join(NOISE.sub("", text.lower().replace("’", "'").replace("'", "")).split())


def hits(cues, query):
    """(from, to, text) for each place the words are said in order, inside one line or across two that follow each other closely."""
    return list(_hits(cues, query))


def _hits(cues, query):
    """Yield matches as needed so a result limit can stop the scan early."""
    wanted = normalize(query)
    if not wanted:
        return
    last = -1
    cached_index, cached_text = -1, ""
    split_query = " " in wanted
    for i, (a, b, text) in enumerate(cues):
        if i <= last:
            continue
        current = cached_text if cached_index == i else normalize(text)
        if wanted in current:
            yield a, b, text
            continue
        # A single normalized word cannot cross the space between subtitle lines.
        if not split_query:
            continue
        nxt = cues[i + 1] if i + 1 < len(cues) else None
        if nxt and nxt[0] - b <= SPLIT_GAP:
            cached_index, cached_text = i + 1, normalize(nxt[2])
            if wanted in f"{current} {cached_text}" and wanted not in cached_text:
                yield a, nxt[1], f"{text} {nxt[2]}"
                last = i + 1


def frame(a, b, scenes, duration):
    """The clip around a spoken line: a little air either side, pulled onto a scene cut when one is close. Also whether a cut was used."""
    start = suggest.snap(max(0.0, a - LEAD), scenes, SNAP_BEFORE, LEAD)
    stop = suggest.snap(min(duration, b + TAIL), scenes, TAIL, SNAP_AFTER)
    snapped = start != max(0.0, a - LEAD) or stop != min(duration, b + TAIL)
    if stop - start < MIN_LEN:
        start, stop, snapped = max(0.0, a - LEAD), min(duration, b + TAIL), False
    return round(start, 2), round(stop, 2), snapped


def search(videos, query, limit=MAX_RESULTS):
    """Hits as [{vid, name, path, in, out, at, text, cut}], earliest episode time first within each video.
    `videos` is [(vid, name, path, duration, cues, scenes)]; a video with no cues is skipped."""
    out = []
    for vid, name, path, duration, cues, scenes in videos:
        scene_index = None
        for a, b, text in _hits(cues or [], query):
            if scene_index is None:
                scene_index = suggest.SceneIndex(scenes or [])
            start, stop, cut = frame(a, b, scene_index, duration)
            out.append({"vid": vid, "name": name, "path": path, "in": start, "out": stop, "at": round(a, 2), "text": text, "cut": cut})
            if len(out) >= limit:
                return out
    return out
