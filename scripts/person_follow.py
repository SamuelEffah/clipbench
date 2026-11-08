"""Follow a person through a stretch of video: find everyone in every frame with YOLO, keep the one inside the box the user drew.

BoT-SORT (shipped with Ultralytics) keeps each person's identity from frame to frame and allows for the camera panning. It is
used for sports footage, where the older single-object tracker loses small, fast players. Positions are fractions of the frame.
"""
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np

MODEL = Path(__file__).parent / "models" / "yolo11n.pt"
FPS = 15
WIDTH = 960
DETECT_SIZE = 1280
CONFIDENCE = 0.25
MAX_PEOPLE = 30  # enough for a court and the first rows of the crowd; cutting the rest short makes duplicate-box removal twice as fast
MIN_OVERLAP = 0.1
CUT_JUMP = 28.0  # mean brightness change across a small copy of the frame that counts as a cut by itself
CUT_LINEUP = 0.3  # share of points that must still line up after a pan; fewer means a new shot
SIZE_RANGE = (0.6, 1.6)  # how much taller or shorter than the picked person a lookalike may be
MAX_SAMPLES = 100
BACK_JPEG_QUALITY = 85
CACHE_DIR = None  # set by the server: where each leg's detected people are kept, so another box on the same stretch is quick
CACHE_KEEP = 40
DISTANCE_COST = 0.3  # how much a lookalike's score drops at the farthest allowed distance
SAME_LOOK = 0.6  # colour match (-1 to 1) a person needs with the one picked to be taken for them
REACQUIRE_WINDOW = 1.0  # seconds after losing the picked person that lookalikes are still considered; later the crop just holds
MAX_JUMP = 0.2  # farthest, in frame widths, the picked person may be from where they were last seen when found again


class NoPerson(ValueError):
    """Nobody was found inside the box."""


def available():
    return MODEL.is_file()


def read_frames(src, start, end, fps=FPS, width=WIDTH):
    """Yield (time, BGR frame) between start and end, `fps` a second."""
    from reframe import probe_size
    w, h = probe_size(src)
    out_w, out_h = width, max(2, round(h * width / w / 2) * 2)
    cmd = ["ffmpeg", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(src), "-an",
           "-vf", f"fps={fps},scale={out_w}:{out_h},format=bgr24", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = out_w * out_h * 3
    try:
        n = 0
        while True:
            raw = proc.stdout.read(size)
            if len(raw) < size:
                break
            yield start + n / fps, np.frombuffer(raw, np.uint8).reshape(out_h, out_w, 3)
            n += 1
    finally:
        proc.stdout.close()
        proc.kill()


def is_cut(prev, frame):
    """True when the two frames are different shots. A pan moves the whole picture together, so most points still line up
    afterwards; a cut leaves almost none that do, even between two views of the same court."""
    import cv2
    small = [cv2.cvtColor(cv2.resize(f, (320, 180), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY) for f in (prev, frame)]
    if float(np.abs(small[0].astype(np.int16) - small[1].astype(np.int16)).mean()) > CUT_JUMP:
        return True
    points = cv2.goodFeaturesToTrack(small[0], maxCorners=150, qualityLevel=0.01, minDistance=6)
    if points is None or len(points) < 12:
        return False
    moved, ok, err = cv2.calcOpticalFlowPyrLK(small[0], small[1], points, None)
    kept = ok.flatten() == 1
    if kept.sum() < 8:
        return True
    _, inliers = cv2.estimateAffinePartial2D(points[kept], moved[kept], method=cv2.RANSAC, ransacReprojThreshold=3.0)
    return inliers is None or float(inliers.sum()) / len(points) < CUT_LINEUP


def overlap(a, b):
    """Intersection over union of two (x1, y1, x2, y2) boxes."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def pick_person(people, box):
    """The id of the person that best matches box (x1, y1, x2, y2), or None. A person whose middle is inside the box counts when no one overlaps enough."""
    best = max(people, key=lambda p: overlap(p[1], box), default=None)
    if best and overlap(best[1], box) >= MIN_OVERLAP:
        return best[0]
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    inside = [p for p in people if box[0] <= (p[1][0] + p[1][2]) / 2 <= box[2] and box[1] <= (p[1][1] + p[1][3]) / 2 <= box[3]]
    near = min(inside, key=lambda p: ((p[1][0] + p[1][2]) / 2 - cx) ** 2 + ((p[1][1] + p[1][3]) / 2 - cy) ** 2, default=None)
    return near[0] if near else None


def people_in(result):
    """[(id, (x1, y1, x2, y2))] for the tracked people in one result."""
    boxes = result.boxes
    if boxes is None or boxes.id is None:
        return []
    return [(int(i), tuple(float(v) for v in b)) for i, b in zip(boxes.id.cpu().numpy(), boxes.xyxy.cpu().numpy())]


def signature(frame, box):
    """What a person looks like: a colour histogram of their torso (hue, saturation and brightness), so a jersey tells them from the other team."""
    import cv2
    x1, y1, x2, y2 = (int(v) for v in box)
    w, h = x2 - x1, y2 - y1
    torso = frame[max(0, y1 + int(h * 0.15)):max(1, y1 + int(h * 0.6)), max(0, x1 + int(w * 0.2)):max(1, x1 + int(w * 0.8))]
    if torso.size == 0:
        return None
    hist = cv2.calcHist([cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)], [0, 1, 2], None, [12, 4, 8], [0, 180, 0, 256, 0, 256])
    return cv2.normalize(hist, hist).flatten()


def likeness(a, b):
    import cv2
    if a is None or b is None:
        return 0.0
    return float(cv2.compareHist(a.astype(np.float32), b.astype(np.float32), cv2.HISTCMP_CORREL))


def choose(people, target, last, look, frame):
    """Who the picked person is in this frame: the tracker's person while they still look the same, else the nearest one that does.
    Returns (id, box), or (target, None) when they cannot be found."""
    h, w = frame.shape[:2]
    mine = next((p for p in people if p[0] == target), None)
    if mine and likeness(signature(frame, mine[1]), look) >= SAME_LOOK:
        return mine
    cx, cy = (last[0] + last[2]) / 2, (last[1] + last[3]) / 2
    tall = last[3] - last[1]
    close = [p for p in people if abs((p[1][0] + p[1][2]) / 2 - cx) <= MAX_JUMP * w and abs((p[1][1] + p[1][3]) / 2 - cy) <= MAX_JUMP * w
             and SIZE_RANGE[0] <= (p[1][3] - p[1][1]) / max(tall, 1) <= SIZE_RANGE[1]]
    scored = [(likeness(signature(frame, p[1]), look), p) for p in close]
    scored = [(l - DISTANCE_COST * max(abs((p[1][0] + p[1][2]) / 2 - cx), abs((p[1][1] + p[1][3]) / 2 - cy)) / (MAX_JUMP * w), p)
              for l, p in scored if l >= SAME_LOOK]
    return max(scored, key=lambda sp: sp[0])[1] if scored else (target, None)


def device():
    import torch
    return "mps" if torch.backends.mps.is_available() else "cpu"


def detections(frames, model_factory, remember=None):
    """Yield (time, frame, people) running the detector on every frame. `remember` gets the people of every frame once the leg is complete."""
    model, dev, seen = model_factory(), device(), []
    for t, frame in frames:
        result = model.track(frame, persist=True, tracker="botsort.yaml", classes=[0], conf=CONFIDENCE, imgsz=DETECT_SIZE,
                             max_det=MAX_PEOPLE, device=dev, verbose=False)[0]
        people = people_in(result)
        seen.append(people)
        yield t, frame, people
    if remember:
        remember(seen)


def replayed(frames, known):
    """The same stream from people found earlier: the frames are read again but nothing is detected."""
    for (t, frame), people in zip(frames, known):
        yield t, frame, people


def run_leg(frames, box, model_factory, progress=None, cache=None):
    """Follow the person in `box` (fractions of the first frame) through frames in order, as [{t, x, y, w, h}].
    The first frame decides who is followed. When that person is lost or the shot cuts, the last position is held.
    `cache` is a (load, save) pair for the people found in this leg, so asking again with another box skips the detector."""
    known = cache[0]() if cache else None
    stream = replayed(frames, known) if known else detections(frames, model_factory, cache[1] if cache else None)
    samples, target, last, prev, look, lost = [], None, None, None, None, None
    for t, frame, people in stream:
        h, w = frame.shape[:2]
        if prev is not None and is_cut(prev, frame):
            target = -1
        prev = frame
        if last is None:
            want = (box["x"] * w, box["y"] * h, (box["x"] + box["w"]) * w, (box["y"] + box["h"]) * h)
            target = pick_person(people, want)
            if target is None:
                raise NoPerson("Couldn't find a person inside that box")
            last = dict(people)[target]
            look = signature(frame, last)
        elif target != -1:
            target, found = choose(people, target, last, look, frame)
            lost = None if found else (t if lost is None else lost)
            if found:
                last = found
            elif t - lost > REACQUIRE_WINDOW:
                target = -1
        x1, y1, x2, y2 = last
        samples.append({"t": round(t, 2), "x": (x1 + x2) / 2 / w, "y": (y1 + y2) / 2 / h, "w": (x2 - x1) / w, "h": (y2 - y1) / h})
        if progress:
            progress()
    return aligned(samples, box)


def aligned(samples, box):
    """The samples moved so the first one sits at the middle of the box the user drew: the crop keeps the subject where they put it."""
    if not samples:
        return samples
    dx, dy = box["x"] + box["w"] / 2 - samples[0]["x"], box["y"] + box["h"] / 2 - samples[0]["y"]
    return [{**s, "x": round(s["x"] + dx, 4), "y": round(s["y"] + dy, 4), "w": round(s["w"], 4), "h": round(s["h"], 4)} for s in samples]


def thin(samples, limit=MAX_SAMPLES):
    """At most `limit` samples, evenly spread in time, keeping the first and last."""
    if len(samples) <= limit:
        return samples
    step = (len(samples) - 1) / (limit - 1)
    return [samples[round(i * step)] for i in range(limit)]


def stored(frames):
    """JPEG-compressed copy of frames, so a long backward leg does not hold gigabytes of raw pictures."""
    import cv2
    return [(t, cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, BACK_JPEG_QUALITY])[1]) for t, f in frames]


def restored(kept):
    import cv2
    return ((t, cv2.imdecode(buf, 1)) for t, buf in kept)


def leg_cache(src, start, end, forward):
    """(load, save) for one leg's people, kept in CACHE_DIR, or None when there is no folder to keep them in. The key holds
    everything that changes what the detector finds, so a changed setting or video never reads an old answer."""
    if CACHE_DIR is None:
        return None
    try:
        stamp = f"{Path(src).stat().st_mtime_ns}|{MODEL.stat().st_mtime_ns}"
    except OSError:
        return None
    key = hashlib.sha1(f"{src}|{stamp}|{start:.3f}|{end:.3f}|{forward}|{FPS}|{WIDTH}|{DETECT_SIZE}|{CONFIDENCE}|{MAX_PEOPLE}".encode()).hexdigest()[:20]
    path = Path(CACHE_DIR) / f"{key}.json"

    def load():
        try:
            return [[(int(p[0]), tuple(p[1:])) for p in frame] for frame in json.loads(path.read_text())]
        except (OSError, ValueError, IndexError, TypeError):
            return None

    def save(seen):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps([[[i, *(round(v, 1) for v in b)] for i, b in frame] for frame in seen]))
            prune(path.parent)
        except OSError:
            pass
    return load, save


def prune(folder, keep=CACHE_KEEP):
    """Keep only the newest `keep` saved legs."""
    files = sorted(folder.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        old.unlink(missing_ok=True)


def follow_person(src, start, end, box, at=None, frames=None, model_factory=None, progress=None):
    """Follow the person inside box ({x, y, w, h} as fractions of the frame at time `at`) through [start, end].

    Returns {"samples"} in time order, forwards and backwards from `at`. Raises NoPerson when no one is in the box.
    `progress(done, total)` is called as frames are finished."""
    at = start if at is None else at
    if model_factory is None:
        def model_factory():
            from ultralytics import YOLO
            return YOLO(str(MODEL))
    done, total = [0], [max(1, round((end - start) * FPS))]

    def step():
        done[0] += 1
        progress(min(done[0], total[0]), total[0])
    step = step if progress else None
    if frames is not None:
        looked = list(frames)
        total[0] = max(1, len(looked))
        ref = min(range(len(looked)), key=lambda n: abs(looked[n][0] - at))
        forward = run_leg(looked[ref:], box, model_factory, step)
        back = run_leg(looked[:ref + 1][::-1], box, model_factory, step)[1:][::-1]
    else:
        forward = run_leg(read_frames(src, at, end), box, model_factory, step, leg_cache(src, at, end, True))
        back = []
        if at - start > 1 / FPS:
            kept = stored(read_frames(src, start, at + 0.5 / FPS))
            back = run_leg(restored(kept[::-1]), box, model_factory, step, leg_cache(src, start, at, False))[1:][::-1]
    return {"samples": thin(back + forward)}
