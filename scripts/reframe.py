"""Find where the face is in a stretch of video, for the bench's AI reframe.

Frames are sampled about once a second with ffmpeg, a face detector looks at each, and the largest face per sample
is kept. Positions are fractions of the source frame, so the caller can map them into any crop.
"""
import statistics
import subprocess
from pathlib import Path

SAMPLE_WIDTH = 480
MAX_SAMPLES = 90
MAX_SPAN = 180.0
MIN_HIT_SHARE = 0.3
ANIME_CASCADE = Path(__file__).parent / "models" / "lbpcascade_animeface.xml"


def probe_size(src):
    """The (width, height) of a video's first stream, by ffprobe."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(src)], capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


def sample_step(span):
    """Seconds between samples: one a second, thinned out for long stretches so there are at most MAX_SAMPLES."""
    return max(1.0, span / MAX_SAMPLES)


def read_frames(src, start, end, step=None):
    """Yield (time, gray frame as a numpy array) between start and end of the source, about once a second unless step says otherwise."""
    import numpy as np
    width, height = probe_size(src)
    w = SAMPLE_WIDTH
    h = max(2, round(height * w / width / 2) * 2)
    step = step or sample_step(end - start)
    cmd = ["ffmpeg", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(src), "-an",
           "-vf", f"fps=1/{step:.3f},scale={w}:{h},format=gray", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    try:
        n = 0
        while True:
            raw = proc.stdout.read(w * h)
            if len(raw) < w * h:
                break
            yield start + n * step, np.frombuffer(raw, np.uint8).reshape(h, w)
            n += 1
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()


def cascade_detector():
    """A detector for faces in a gray frame: the anime cascade when it has been added to scripts/models, then OpenCV's own."""
    import cv2
    paths = ([str(ANIME_CASCADE)] if ANIME_CASCADE.is_file() else []) + [cv2.data.haarcascades + "haarcascade_frontalface_default.xml"]
    cascades = [cv2.CascadeClassifier(p) for p in paths]

    def detect(gray):
        small = max(24, gray.shape[1] // 16)
        eq = cv2.equalizeHist(gray)
        for c in cascades:
            found = c.detectMultiScale(eq, scaleFactor=1.1, minNeighbors=4, minSize=(small, small))
            if len(found):
                return [tuple(int(v) for v in f) for f in found]
        return []
    return detect


def largest(faces):
    """The biggest of (x, y, w, h) faces, or None."""
    return max(faces, key=lambda f: f[2] * f[3]) if faces else None


def sample_of(t, face, frame_w, frame_h):
    """One detection as fractions of the frame: its centre, width and height."""
    x, y, w, h = face
    return {"t": round(t, 2), "x": round((x + w / 2) / frame_w, 4), "y": round((y + h / 2) / frame_h, 4),
            "w": round(w / frame_w, 4), "h": round(h / frame_h, 4)}


def summarize(samples, total):
    """The typical face over a stretch (the median), or None when too few frames had one to trust."""
    if not samples or len(samples) < max(1, total * MIN_HIT_SHARE):
        return None
    return {key: round(statistics.median(s[key] for s in samples), 4) for key in ("x", "y", "w", "h")}


def find_faces(src, start, end, frames=None, detector=None):
    """Look for the face across [start, end] of a video. Returns {"found", "face", "samples", "looked"}."""
    if not 0 <= start < end or end - start > MAX_SPAN:
        raise ValueError(f"Pick a clip under {MAX_SPAN:g} seconds")
    detector = detector or cascade_detector()
    samples, looked = [], 0
    for t, gray in (frames if frames is not None else read_frames(src, start, end)):
        looked += 1
        face = largest(detector(gray))
        if face:
            samples.append(sample_of(t, face, gray.shape[1], gray.shape[0]))
    face = summarize(samples, looked)
    return {"found": face is not None, "face": face, "samples": samples if face else [], "looked": looked}


FOLLOW_MIN_STEP = 0.25
FOLLOW_SAMPLES = 100


def follow_step(span):
    """Seconds between looks when following a subject: four a second, thinned for long stretches to keep FOLLOW_SAMPLES."""
    return max(FOLLOW_MIN_STEP, span / FOLLOW_SAMPLES)


def mil_tracker(gray, box):
    """OpenCV's MIL tracker started on a gray frame at (x, y, w, h) pixels."""
    import cv2
    tracker = cv2.TrackerMIL_create()
    tracker.init(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), tuple(int(v) for v in box))

    class Wrapped:
        def update(self, frame):
            return tracker.update(cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR))
    return Wrapped()


REMATCH_SCORE = 0.6


def rematch(gray, last, template, min_score=REMATCH_SCORE):
    """Look for a lost subject by its look: the (x, y, w, h) where the template fits best in the frame, or None when nothing fits."""
    import cv2
    th, tw = template.shape
    if template.std() < 1 or gray.shape[0] < th or gray.shape[1] < tw:
        return None
    scores = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
    _, best, _, where = cv2.minMaxLoc(scores)
    if not best >= min_score:
        return None
    return (where[0], where[1], tw, th)


def run_track(frames, box, make_tracker):
    """Follow box (fractions of the first frame) through frames in order. A lost subject is searched for by its look, else held."""
    samples, tracker, last, template = [], None, None, None
    for t, gray in frames:
        h, w = gray.shape
        if tracker is None:
            last = (box["x"] * w, box["y"] * h, box["w"] * w, box["h"] * h)
            tracker = make_tracker(gray, last)
            x, y, bw, bh = (int(v) for v in last)
            template = gray[y:y + bh, x:x + bw].copy()
        else:
            ok, found = tracker.update(gray)
            if ok and found[2] > 0 and found[3] > 0:
                last = tuple(found)
            else:
                again = rematch(gray, last, template)
                if again:
                    last = again
                    tracker = make_tracker(gray, last)
        samples.append(sample_of(t, last, w, h))
    return samples


def follow_subject(src, start, end, box, frames=None, make_tracker=None, at=None):
    """Follow what is inside box ({x, y, w, h} as fractions of the frame at time `at`, default start) through [start, end].

    Returns {"samples"}, one per look in time order, forwards and backwards from `at`.
    """
    at = start if at is None else at
    if not 0 <= start < end or end - start > MAX_SPAN:
        raise ValueError(f"Pick a clip under {MAX_SPAN:g} seconds")
    if not start <= at <= end:
        raise ValueError("The reference frame has to be inside the clip")
    if not (0 <= box["x"] and 0 <= box["y"] and box["w"] > 0 and box["h"] > 0 and box["x"] + box["w"] <= 1 and box["y"] + box["h"] <= 1):
        raise ValueError("The box has to sit inside the frame")
    make_tracker = make_tracker or mil_tracker
    step = follow_step(end - start)
    begin = at - int((at - start) / step + 1e-6) * step
    looked = list(frames) if frames is not None else list(read_frames(src, begin, end, step))
    ref = min(range(len(looked)), key=lambda n: abs(looked[n][0] - at)) if looked else 0
    forward = run_track(looked[ref:], box, make_tracker)
    back = run_track(looked[:ref + 1][::-1], box, make_tracker)[1:][::-1]
    return {"samples": back + forward}
