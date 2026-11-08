"""Follow whoever is talking: find every face, watch each mouth, and keep the crop on the face that moves while words are spoken.

YuNet (shipped with OpenCV) gives each face and its mouth corners. A face keeps one identity across frames, its mouth is cut
out of every frame, and how much that patch changes from frame to frame says how much the mouth is moving. The crop stays
on a speaker until another face has been the one moving for HOLD seconds, then jumps. Positions are fractions of the frame.
"""
import statistics
import subprocess
from pathlib import Path

import numpy as np

MODEL = Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"
FPS = 10
WIDTH = 640
SCORE = 0.7
LINK_REACH = 1.2  # farthest, in face widths, a face may move between looks and still be the same one
LOST_AFTER = 1.0  # seconds a face may go unseen before its next sighting counts as someone new
PATCH = (24, 12)  # mouth cut-out size the motion is measured on
WINDOW = 0.8  # seconds of mouth movement averaged into one reading
HOLD = 1.5  # seconds another face has to keep winning before the crop moves to it
RAMP = 0.2  # seconds the crop takes to travel to a new speaker
MIN_MOTION = 0.012  # least average patch change that counts as a moving mouth
LEAD = 1.5  # how many times more a face must move than the next to win while two are in view
WORD_PAD = 0.15  # seconds of speech assumed either side of a word
MIN_SPEECH_SHARE = 0.1  # share of the clip someone must be seen speaking for the answer to be trusted
MAX_SPAN = 180.0


class NoFaces(ValueError):
    """No face was found in the clip."""


def available():
    return MODEL.is_file()


def yunet(width, height):
    import cv2
    return cv2.FaceDetectorYN.create(str(MODEL), "", (width, height), SCORE, 0.3, 10)


def detect_faces(detector, frame):
    """The faces in a BGR frame as dicts: box (x, y, w, h) and mouth (cx, cy, w, h), in pixels."""
    h, w = frame.shape[:2]
    detector.setInputSize((w, h))
    _, found = detector.detect(frame)
    faces = []
    for row in (found if found is not None else []):
        x, y, bw, bh = (float(v) for v in row[:4])
        left, right = (float(row[10]), float(row[11])), (float(row[12]), float(row[13]))
        width = max(abs(left[0] - right[0]), bw * 0.25) * 1.4
        faces.append({"box": (x, y, bw, bh), "mouth": ((left[0] + right[0]) / 2, (left[1] + right[1]) / 2, width, width * 0.6)})
    return faces


def mouth_patch(gray, mouth):
    """The mouth cut out of a gray frame at a fixed size, brightness taken out so lighting changes do not read as movement."""
    import cv2
    cx, cy, w, h = mouth
    x0, y0 = max(0, int(cx - w / 2)), max(0, int(cy - h / 2))
    x1, y1 = min(gray.shape[1], int(cx + w / 2)), min(gray.shape[0], int(cy + h / 2))
    if x1 - x0 < 4 or y1 - y0 < 3:
        return None
    patch = cv2.resize(gray[y0:y1, x0:x1], PATCH, interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    return patch - patch.mean()


def movement(a, b):
    """How much one mouth patch differs from the previous one, 0 when either is missing."""
    return 0.0 if a is None or b is None else float(np.abs(a - b).mean())


def centre(face):
    x, y, w, h = face["box"]
    return x + w / 2, y + h / 2


def link(tracks, faces, t, frame_w, frame_h, gray):
    """Hand each face to the track it continues, nearest first, and start a track for any left over. Returns the tracks."""
    pairs = []
    for ti, track in enumerate(tracks):
        if t - track["last_t"] > LOST_AFTER:
            continue
        for fi, face in enumerate(faces):
            fx, fy = centre(face)
            d = ((fx - track["cx"]) ** 2 + (fy - track["cy"]) ** 2) ** 0.5
            if d <= LINK_REACH * max(face["box"][2], track["w"]):
                pairs.append((d, ti, fi))
    taken_t, taken_f = set(), {}
    for _, ti, fi in sorted(pairs):
        if ti not in taken_t and fi not in taken_f:
            taken_t.add(ti)
            taken_f[fi] = ti
    for fi, face in enumerate(faces):
        if fi not in taken_f:
            tracks.append({"id": len(tracks), "samples": [], "patch": None, "last_t": t, "cx": 0.0, "cy": 0.0, "w": 0.0})
            taken_f[fi] = len(tracks) - 1
    for fi, face in enumerate(faces):
        track = tracks[taken_f[fi]]
        cx, cy = centre(face)
        patch = mouth_patch(gray, face["mouth"])
        moved = movement(track["patch"], patch) if t - track["last_t"] <= 2.0 / FPS else 0.0
        track["samples"].append({"t": round(t, 2), "x": round(cx / frame_w, 4), "y": round(cy / frame_h, 4),
                                 "w": round(face["box"][2] / frame_w, 4), "h": round(face["box"][3] / frame_h, 4), "move": moved})
        track.update(patch=patch, last_t=t, cx=cx, cy=cy, w=face["box"][2])
    return tracks


def find_tracks(frames, detector, is_cut=None):
    """Every face seen in frames ((time, BGR frame) pairs), as tracks with a position and mouth movement per look.

    A cut to another shot ends every track, so a face in the new shot is never taken for one from the last. Returns
    (tracks, looked, cuts), where cuts are the times each new shot starts.
    """
    import cv2
    if is_cut is None:
        from person_follow import is_cut
    tracks, looked, cuts, prev = [], 0, [], None
    for t, frame in frames:
        looked += 1
        if prev is not None and is_cut(prev, frame):
            cuts.append(round(t, 2))
            for track in tracks:
                track["last_t"] = float("-inf")
        prev = frame
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        link(tracks, detect_faces(detector, frame), t, frame.shape[1], frame.shape[0], gray)
    return tracks, looked, cuts


def shot_bounds(times, cuts):
    """The (first, last) index into times of each shot."""
    starts = set(cuts)
    edges = [0] + [i for i, t in enumerate(times) if t in starts] + [len(times)]
    return [(a, b - 1) for a, b in zip(edges, edges[1:]) if b > a]


def speech_flags(times, words, start, pad=WORD_PAD):
    """Whether someone is talking at each time, from words timed in seconds from `start`: [word, from, to]."""
    spans = [(start + w[1] - pad, start + w[2] + pad) for w in words]
    return [any(a <= t <= b for a, b in spans) for t in times]


def loudness_flags(src, start, end, times, rate=16000):
    """Whether the sound is up at each time, for clips whose words are not known yet. The threshold follows the clip's own level."""
    cmd = ["ffmpeg", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(src), "-vn", "-ac", "1",
           "-ar", str(rate), "-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    audio = np.frombuffer(raw[: len(raw) // 2 * 2], np.int16).astype(np.float32) / 32768.0
    step = rate // FPS
    levels = [float(np.sqrt(np.mean(audio[i:i + step] ** 2))) for i in range(0, len(audio) - step + 1, step)]
    if not levels:
        return [False] * len(times)
    limit = max(0.008, 0.25 * float(np.percentile(levels, 90)))
    return [levels[min(len(levels) - 1, max(0, int((t - start) * FPS)))] > limit for t in times]


def smoothed_moves(track, times):
    """A track's mouth movement at each time, averaged over WINDOW; 0 where the face was not in view."""
    seen = {s["t"]: s["move"] for s in track["samples"]}
    half = max(1, round(WINDOW * FPS / 2))
    out = []
    for i in range(len(times)):
        near = [seen.get(round(times[j], 2), 0.0) for j in range(max(0, i - half), min(len(times), i + half + 1))]
        out.append(sum(near) / len(near))
    return out


def winners(tracks, times, talking):
    """Who is speaking at each time: a track id, or None when nobody is talking or nobody clearly leads."""
    moves = {t["id"]: smoothed_moves(t, times) for t in tracks}
    out = []
    for i in range(len(times)):
        if not talking[i]:
            out.append(None)
            continue
        ranked = sorted(((m[i], tid) for tid, m in moves.items()), reverse=True)
        best = ranked[0] if ranked else (0.0, None)
        if best[0] < MIN_MOTION or (len(ranked) > 1 and best[0] < LEAD * ranked[1][0]):
            out.append(None)
        else:
            out.append(best[1])
    return out


def segments(times, who, hold=HOLD):
    """Spans [start, end, id] of who the crop stays on. It moves to a new face only after that face wins for `hold` seconds."""
    step = 1.0 / FPS
    spans, current, challenger, since = [], None, None, 0.0
    for t, w in zip(times, who):
        if w is None:
            continue
        if w == current:
            challenger = None
            continue
        if current is None:
            current = w
            spans.append([times[0], t, w])
            continue
        if w != challenger:
            challenger, since = w, t
        if t - since + step >= hold:
            spans[-1][1] = since
            spans.append([since, since, w])
            current, challenger = w, None
    if current is None:
        return []
    spans[-1][1] = times[-1]
    spans[0][0] = times[0]
    for a, b in zip(spans, spans[1:]):
        a[1] = b[0]
    return spans


def biggest_in(tracks, times, lo, hi):
    """The track with the most looks in times[lo] to times[hi], or None: whoever is on screen when nobody is clearly talking."""
    a, b = times[lo], times[hi]
    seen = [(sum(1 for q in t["samples"] if a <= q["t"] <= b), t["id"]) for t in tracks]
    best = max(seen, default=(0, None))
    return best[1] if best[0] else None


def shot_spans(tracks, times, who, cuts):
    """Spans [start, end, id, cut] for the whole clip. The hold applies inside a shot only: at a cut the crop goes at once to
    whoever is talking in the new shot, or to the face with most screen time there when nobody clearly is."""
    spans = []
    for n, (lo, hi) in enumerate(shot_bounds(times, cuts)):
        inside = segments(times[lo:hi + 1], who[lo:hi + 1])
        if not inside:
            tid = biggest_in(tracks, times, lo, hi)
            inside = [[times[lo], times[hi], tid]] if tid is not None else []
        for span in inside:
            spans.append([*span, n > 0 and span is inside[0]])
    return spans


def calm(samples, size=5):
    """Positions with a rolling median over `size` looks, so one stray detection does not tug the crop."""
    half = size // 2
    return [{"t": s["t"], "x": round(statistics.median(n["x"] for n in samples[max(0, i - half): i + half + 1]), 4),
             "y": round(statistics.median(n["y"] for n in samples[max(0, i - half): i + half + 1]), 4)} for i, s in enumerate(samples)]


def position_at(samples, t):
    """Where a calmed track was at time t: the nearest look to it."""
    return min(samples, key=lambda s: abs(s["t"] - t))


def crop_track(tracks, spans, ramp=RAMP):
    """Keyframes {t, x, y} that sit on the speaker in each span. A new speaker is reached over `ramp` seconds, or at once when
    the span starts at a cut."""
    calmed = {t["id"]: calm(t["samples"]) for t in tracks if t["samples"]}
    keys = []
    for a, b, tid, *cut in spans:
        samples = calmed.get(tid)
        if not samples:
            continue
        slow = bool(keys) and not (cut and cut[0])
        if keys and cut and cut[0]:
            keys.append({"t": round(a - 0.01, 2), "x": keys[-1]["x"], "y": keys[-1]["y"]})
        if slow:
            keys.append({"t": round(a, 2), "x": keys[-1]["x"], "y": keys[-1]["y"]})
            first = position_at(samples, a + ramp)
            keys.append({"t": round(a + ramp, 2), "x": first["x"], "y": first["y"]})
        keys.extend(s for s in samples if (a + ramp < s["t"] if slow else a <= s["t"]) and s["t"] <= b)
    return keys


def speakers_summary(tracks, who):
    """One entry per face that spoke: where it sits, how big, and how many seconds it was the speaker."""
    out = []
    for track in tracks:
        talk = sum(1 for w in who if w == track["id"]) / FPS
        if talk <= 0:
            continue
        keys = ("x", "y", "w", "h")
        out.append({"id": track["id"], "seconds": round(talk, 1),
                    **{k: round(statistics.median(s[k] for s in track["samples"]), 4) for k in keys}})
    return sorted(out, key=lambda s: -s["seconds"])


def follow_speaker(src, start, end, words=None, frames=None, detector=None, talking=None, is_cut=None):
    """Find who is talking across [start, end] of a video and where the crop should sit.

    `words` are [word, from, to] timed from `start` when known; otherwise the sound level stands in for speech.
    Returns {"found", "face", "speakers", "samples", "track"}; face is the typical speaker, for working out the zoom.
    """
    if not 0 <= start < end or end - start > MAX_SPAN:
        raise ValueError(f"Pick a clip under {MAX_SPAN:g} seconds")
    if frames is None:
        from person_follow import read_frames
        frames = read_frames(src, start, end, FPS, WIDTH)
        from reframe import probe_size
        w, h = probe_size(src)
        detector = detector or yunet(WIDTH, max(2, round(h * WIDTH / w / 2) * 2))
    tracks, looked, cuts = find_tracks(frames, detector, is_cut)
    times = [round(start + n / FPS, 2) for n in range(looked)]
    if talking is None:
        talking = speech_flags(times, words, start) if words else loudness_flags(src, start, end, times)
    who = winners(tracks, times, talking)
    spans = shot_spans(tracks, times, who, cuts) if sum(1 for w in who if w is not None) >= max(1, looked * MIN_SPEECH_SHARE) else []
    if not spans:
        return {"found": False, "face": None, "speakers": [], "samples": [], "track": []}
    speakers = speakers_summary(tracks, who)
    keys = ("x", "y", "w", "h")
    face = {k: round(statistics.median(s[k] for s in speakers), 4) for k in keys}
    track = crop_track(tracks, spans)
    return {"found": bool(track), "face": face if track else None, "speakers": speakers, "samples": track, "track": track}
