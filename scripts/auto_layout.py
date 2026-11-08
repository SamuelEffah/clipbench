"""Pick a Short layout for a clip from who is in it: two people, a streamer's webcam over gameplay, one person, or none."""
import statistics

import numpy as np

from speaker_follow import MODEL, available, detect_faces, yunet  # noqa: F401  (available is re-exported for the server)

FPS = 2
WIDTH = 640
MAX_SPAN = 180.0
MIN_SEEN = 0.4  # share of the looks a face must turn up in to count as part of the clip
SAME_FACE = 1.0  # farthest, in face widths, a face may sit from a known one and still be it
SIMILAR = 0.55  # smallest size ratio between people for them to share the frame as equals
CAM_FACE = 0.22  # widest a webcam's face is, as a share of the frame width
CAM_CORNER = 0.32  # how close to the frame's edge, as a share of each side, a webcam's face sits: a face sits in the upper half of a big corner cam
CAM_STEADY = 0.03  # most a webcam face may drift, as a share of the frame
CAM_SCALE = (2.2, 2.3)  # webcam size as a multiple of the face box: width, height
SNAP = 0.04  # a webcam edge this near the frame edge sits on it
MAX_PEOPLE = 4
SAME_SPOT = 0.08  # farthest apart, as a share of the frame, two shots' faces or webcams may be and share one crop
SAME_CAM = 0.15  # the same for webcam rectangles, whose edges are found less exactly than a face
SAME_RECT = 0.8  # share of their joint area two webcam rectangles must both cover to be one cam read twice
MIN_SEGMENT = 1.5  # seconds; a shorter stretch is folded into its neighbour
EDGE_STEP = 2  # pixels either side of a column or row compared when looking for a webcam's border
EDGE_JUMP = 20  # least brightness change that counts as part of a border
SUBSETS = 3  # interleaved parts of the looks the border evidence is checked on as well as the whole
EDGE_SHARE = 0.3  # share of a border's length that must jump for it to count
EDGE_STAND_OUT = 0.2  # how far above the lines around it a border's share must sit
TIE = 0.02  # borders this close in strength are equals, and the nearer to the face wins
PEAK = 3  # lines either side a border must beat
FAR = 12  # lines either side that count as "around" it
CAM_VS_FACE = (10, 5)  # most a webcam may be, as a multiple of its face box's width and height: a streamer sitting back from a wide cam is a small face in it
SIDE_BAND = 1.5  # face heights above and below the face a side webcam's vertical border is looked for along
FACE_MARGIN = 0.02  # room a webcam leaves between its face and its inner edges, as a share of the frame
FACE_CLEAR = 0.4  # room, as a share of the face box's width, a webcam must leave beyond the box at the side. Ears spill out of the box, so a border hugging it is not a webcam's edge
FACE_CLEAR_Y = 0.25  # the same above and below, as a share of the box's height past the face's middle: a border above the eyes can be the cam's top edge, since a streamer's head often reaches it
CANDIDATES = 8  # borders kept per direction to try
CAM_THROUGHOUT = 0.7  # share of the clip a webcam face must be in for one answer to serve the whole clip
CAM_SHAPE = (1.15, 2.2)  # width over height of a webcam as it appears in the picture
CAM_MAX = (0.5, 0.6)  # biggest a webcam is, as a share of the frame width and height
MAX_LOOKS = 40  # frames kept to average the picture on
STRIP = (3, 9)  # pixels from a border the strip measured for movement starts and ends at


def clusters(looks):
    """Group every face seen into the person it belongs to by where it sits. Each is {"boxes": [...], "frames": n}."""
    people = []
    for n, faces in enumerate(looks):
        for box in faces:
            cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
            near = [p for p in people if ((cx - p["cx"]) ** 2 + (cy - p["cy"]) ** 2) ** 0.5 <= SAME_FACE * max(box[2], p["w"])
                    and p["last"] != n]
            if near:
                p = min(near, key=lambda p: (cx - p["cx"]) ** 2 + (cy - p["cy"]) ** 2)
            else:
                p = {"boxes": [], "frames": 0, "last": -1, "cx": cx, "cy": cy, "w": box[2]}
                people.append(p)
            p["boxes"].append(box)
            p["frames"] += 1
            p["last"] = n
            p["cx"], p["cy"], p["w"] = cx, cy, box[2]
    return people


def typical(person):
    """The median face of a person, as fractions of the frame: centre x, y and the box's width and height."""
    return {k: round(statistics.median(b[i] for b in person["boxes"]), 4) for k, i in (("x", 0), ("y", 1), ("w", 2), ("h", 3))}


def centred(face):
    return {**face, "x": round(face["x"] + face["w"] / 2, 4), "y": round(face["y"] + face["h"] / 2, 4)}


def drift(person):
    """How much a person's face moves about, as a share of the frame."""
    return max(statistics.pstdev(b[0] + b[2] / 2 for b in person["boxes"]), statistics.pstdev(b[1] + b[3] / 2 for b in person["boxes"]))


def by_steadiness(people):
    """The people who hold still enough to be in a webcam, steadiest first: a face in a cam does not move with the game's camera."""
    return sorted((p for p in people if drift(p) <= CAM_STEADY), key=drift)


def is_webcam(face, person):
    cx, cy = face["x"], face["y"]
    in_corner = (cx < CAM_CORNER or cx > 1 - CAM_CORNER) and (cy < CAM_CORNER or cy > 1 - CAM_CORNER)
    return face["w"] <= CAM_FACE and in_corner and drift(person) <= CAM_STEADY


def webcam_rect(face):
    """The rectangle a webcam most likely fills around its face, snapped to the frame edge it sits against."""
    w, h = min(0.6, face["w"] * CAM_SCALE[0]), min(0.6, face["h"] * CAM_SCALE[1])
    x, y = face["x"] - w / 2, face["y"] - h * 0.45
    x, y = min(1 - w, max(0.0, x)), min(1 - h, max(0.0, y))
    if x < SNAP:
        x = 0.0
    if y < SNAP:
        y = 0.0
    if 1 - (x + w) < SNAP:
        x = 1 - w
    if 1 - (y + h) < SNAP:
        y = 1 - h
    return {k: round(v, 4) for k, v in (("x", x), ("y", y), ("w", w), ("h", h))}


def jump_share(pictures, axis, pos, extent):
    """The share of a line (column `pos` for axis 1, row for 0) along `extent` where the picture jumps in brightness, averaged over the pictures."""
    votes = []
    for gray in pictures:
        a, b = (gray[extent, pos + EDGE_STEP], gray[extent, pos - EDGE_STEP]) if axis == 1 else (gray[pos + EDGE_STEP, extent], gray[pos - EDGE_STEP, extent])
        votes.append(float((np.abs(a - b) > EDGE_JUMP).mean()) if len(a) else 0.0)
    return sum(votes) / len(votes)


def strength(pictures, rect):
    """How cleanly a webcam rectangle's borders stand out from the picture: the mean jump share along its edges that are not the frame's own."""
    h, w = pictures[0].shape
    shares = []
    for axis, pos, extent, _ in edges_of(rect, w, h):
        pos = min(max(pos, EDGE_STEP), (w if axis == 1 else h) - EDGE_STEP - 1)
        shares.append(jump_share(pictures, axis, pos, extent))
    return sum(shares) / len(shares) if shares else 0.0


def border(pictures, lines, along, axis):
    """Candidate positions of a straight border among `lines` (columns for axis 1, rows for 0), as pixel indexes, best first.

    Stronger borders come first and, between near equals, the one nearer the face. `lines` run outward from the face; `along` is the slice of the other direction the border should run across. A border
    jumps in much of that length and stands out from the lines just beside it, so busy gameplay alone does not pass.
    """
    scores = [jump_share(pictures, axis, i, along) for i in lines]
    found = []
    for n, v in enumerate(scores):
        near = scores[max(0, n - PEAK) : n + PEAK + 1]
        around = scores[max(0, n - FAR) : max(0, n - PEAK)] + scores[n + PEAK + 1 : n + FAR + 1]
        if v >= EDGE_SHARE and v >= max(near) and v - (sum(around) / len(around) if around else 0.0) >= EDGE_STAND_OUT:
            found.append((n, v))
    ranked = sorted(found, key=lambda t: (-round(t[1] / TIE), t[0]))
    return [lines[n] for n, _ in ranked[:CANDIDATES]]


def motion(grays, axis, pos, extent, outward):
    """How much the strip of picture just to one side of a border changes over the clip: `outward` +1 is beyond it (right of a column, below a row), -1 is before it."""
    stack = np.stack(grays).astype(np.float32)
    lo, hi = (pos + STRIP[0], pos + STRIP[1]) if outward > 0 else (max(0, pos - STRIP[1]), max(0, pos - STRIP[0]))
    strip = stack[:, extent, lo:hi] if axis == 1 else stack[:, lo:hi, extent]
    return float(strip.std(axis=0).mean()) if strip.size else 0.0


def edges_of(rect, w, h):
    """The borders a webcam rectangle makes with the picture, as (axis, pixel position, extent, which side is outside), leaving out the frame's own edges."""
    x0, x1 = int(round(rect["x"] * w)), int(round((rect["x"] + rect["w"]) * w))
    y0, y1 = int(round(rect["y"] * h)), int(round((rect["y"] + rect["h"]) * h))
    rows, cols = slice(y0, y1), slice(x0, x1)
    edges = [(1, x0, rows, -1), (1, x1, rows, 1), (0, y0, cols, -1), (0, y1, cols, 1)]
    return [e for e in edges if 0 < e[1] < (w if e[0] == 1 else h)]


def best_cam(rects, grays):
    """Of the rectangles that could be the webcam, the one with the most movement just outside its borders and the least just inside:
    the game plays on while the cam's own frame holds still. When no rectangle has that (a streamer waving fills the cam with
    movement), the movement says nothing, and the given order stands: strongest border first."""
    if not rects or grays is None or len(rects) < 2:
        return rects[0] if rects else None
    h, w = grays[0].shape
    still_outside = lambda rect: sum(motion(grays, axis, pos, extent, out) - motion(grays, axis, pos, extent, -out) for axis, pos, extent, out in edges_of(rect, w, h))
    best = max(rects, key=still_outside)
    return best if still_outside(best) > 0 else rects[0]


def find_cam(pictures, face, grays=None):
    """The webcam rectangle around a face that sits in a corner, found from the two straight borders it makes with the picture.

    `pictures` are the clip's median pictures (see medians) and `grays` the frames they came from. Returns {x, y, w, h} as fractions, or None when no clear border is there.
    """
    h, w = pictures[0].shape
    left, bottom = face["x"] < 0.5, face["y"] >= 0.5
    # A face at mid height is in a cam that floats against the side, so its own top border is looked for before one is assumed at the frame's edge.
    if CAM_CORNER < face["y"] < 1 - CAM_CORNER and (side := find_side_cam(pictures, face, grays)):
        return side
    if left:
        cols = list(range(int((face["x"] + face["w"] / 2) * w) + 3, int(CAM_MAX[0] * w)))
    else:
        cols = list(range(int((face["x"] - face["w"] / 2) * w) - 3, int((1 - CAM_MAX[0]) * w), -1))
    cols = [c for c in cols if EDGE_STEP <= c < w - EDGE_STEP]
    valid = []
    x_options = border(pictures, cols, slice(int(face["y"] * h), h) if bottom else slice(0, max(1, int(face["y"] * h))), 1)
    for x_edge in x_options:
        across = slice(0, x_edge) if left else slice(x_edge, w)
        rows = list(range(int((face["y"] - 0.01) * h), int((1 - CAM_MAX[1]) * h), -1)) if bottom else list(range(int((face["y"] + 0.01) * h), int(CAM_MAX[1] * h)))
        rows = [r for r in rows if EDGE_STEP <= r < h - EDGE_STEP]
        for y_edge in border(pictures, rows, across, 0):
            x0, x1 = (0.0, x_edge / w) if left else (x_edge / w, 1.0)
            y0, y1 = (y_edge / h, 1.0) if bottom else (0.0, y_edge / h)
            rect = {"x": round(x0, 4), "y": round(y0, 4), "w": round(x1 - x0, 4), "h": round(y1 - y0, 4)}
            if fits_face(rect, face, w / h):
                valid.append(rect)
    if valid:
        return best_cam(valid, grays)
    return find_side_cam(pictures, face, grays)


def find_side_cam(pictures, face, grays=None):
    """The webcam rectangle around a face when the cam floats against a side edge at mid height, touching neither the top nor the bottom.

    One vertical border is looked for along a band of rows around the face, then a top and a bottom border across the width that leaves.
    Returns {x, y, w, h} as fractions, or None.
    """
    h, w = pictures[0].shape
    left = face["x"] < 0.5
    band = slice(max(0, int((face["y"] - SIDE_BAND * face["h"]) * h)), min(h, int((face["y"] + SIDE_BAND * face["h"]) * h)))
    if left:
        cols = list(range(int((face["x"] + face["w"] / 2) * w) + 3, int(CAM_MAX[0] * w)))
    else:
        cols = list(range(int((face["x"] - face["w"] / 2) * w) - 3, int((1 - CAM_MAX[0]) * w), -1))
    cols = [c for c in cols if EDGE_STEP <= c < w - EDGE_STEP]
    up = [r for r in range(int((face["y"] - 0.01) * h), int((face["y"] - CAM_MAX[1]) * h), -1) if EDGE_STEP <= r < h - EDGE_STEP]
    down = [r for r in range(int((face["y"] + 0.01) * h), int((face["y"] + CAM_MAX[1]) * h)) if EDGE_STEP <= r < h - EDGE_STEP]
    valid = []
    for x_edge in border(pictures, cols, band, 1):
        across = slice(0, x_edge) if left else slice(x_edge, w)
        tops, bottoms = border(pictures, up, across, 0), border(pictures, down, across, 0)
        for y_top in tops:
            for y_bottom in bottoms:
                x0, x1 = (0.0, x_edge / w) if left else (x_edge / w, 1.0)
                rect = {"x": round(x0, 4), "y": round(y_top / h, 4), "w": round(x1 - x0, 4), "h": round((y_bottom - y_top) / h, 4)}
                if fits_face(rect, face, w / h):
                    valid.append(rect)
    return best_cam(valid, grays)


def fits_face(rect, face, aspect):
    """Whether a rectangle could be the webcam around a face: it leaves room beside the face on its inner side and below
    or above its middle, is in proportion to the face, has the width-to-height of a webcam, and is no bigger than one gets.
    `aspect` is the picture's width over its height.

    The face box is only held loosely against the rectangle: detectors draw it taller than the face, so the rectangle need
    only clear FACE_CLEAR of its height past the middle, not the whole half.
    """
    left, bottom = face["x"] < 0.5, face["y"] >= 0.5
    gap = max(FACE_MARGIN, FACE_CLEAR * face["w"])
    beside = rect["x"] + rect["w"] >= face["x"] + face["w"] / 2 + gap if left else rect["x"] <= face["x"] - face["w"] / 2 - gap
    room = max(FACE_MARGIN, FACE_CLEAR_Y * face["h"])
    above, below = rect["y"] <= face["y"] - room, rect["y"] + rect["h"] >= face["y"] + room
    floating = rect["y"] > SNAP and rect["y"] + rect["h"] < 1 - SNAP
    along = (above and below) if floating else (above if bottom else below)
    sized = rect["w"] <= CAM_VS_FACE[0] * face["w"] and rect["h"] <= CAM_VS_FACE[1] * face["h"]
    shape = rect["w"] * aspect / rect["h"] if rect["h"] else 0.0
    return beside and along and sized and CAM_SHAPE[0] <= shape <= CAM_SHAPE[1] and rect["w"] <= CAM_MAX[0] and rect["h"] <= CAM_MAX[1]


def reading_order(faces):
    """Left to right, or top to bottom when the people are stacked."""
    xs, ys = [f["x"] for f in faces], [f["y"] for f in faces]
    stacked = (max(ys) - min(ys)) > 1.5 * (max(xs) - min(xs))
    return sorted(faces, key=lambda f: f["y"] if stacked else f["x"])


def inside(face, rect):
    return rect["x"] <= face["x"] <= rect["x"] + rect["w"] and rect["y"] <= face["y"] <= rect["y"] + rect["h"]


def overlap(a, b):
    """The share of the area the two rectangles cover together that both of them cover."""
    w = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    h = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
    both = max(0.0, w) * max(0.0, h)
    either = a["w"] * a["h"] + b["w"] * b["h"] - both
    return both / either if either else 0.0


def holds(pictures, cam):
    """Whether a cam remembered from another clip of the stream still shows its border in this one."""
    return pictures is not None and cam is not None and strength(pictures, cam) >= EDGE_SHARE


def recalled(cam, faces):
    """The stream's remembered cam as the answer, with whichever faces sit in it."""
    return {"layout": "webcam", "faces": [{k: f[k] for k in "xywh"} for f in faces if inside(f, cam)], "webcam": cam, "guessed": False,
            "remembered": True, "share": 1.0, "reason": "The stream's webcam, remembered from an earlier clip"}


def decide(looks, pictures=None, grays=None, remembered=None):
    seen = [p for p in clusters(looks) if p["frames"] >= max(1, len(looks) * MIN_SEEN)]
    if not seen:
        if holds(pictures, remembered):
            return recalled(remembered, [])
        return {"layout": "none", "faces": [], "webcam": None, "reason": "No face in the clip"}
    seen.sort(key=lambda p: -statistics.median(b[2] for b in p["boxes"]))
    faces = [centred(typical(p)) for p in seen]
    big = faces[0]
    framed = []
    for person in by_steadiness(seen) if pictures is not None else []:
        face = centred(typical(person))
        if face["w"] > CAM_FACE:
            continue
        cam, guessed = find_cam(pictures, face, grays), False
        if cam and remembered and overlap(cam, remembered) >= SAME_RECT:
            # All but the stream's known cam: a border read a little off on a busy or dark picture. The known one keeps every clip's crop the same.
            cam = remembered
        if not cam and face["w"] >= big["w"] * SIMILAR and is_webcam(face, person) and person["frames"] >= len(looks) * CAM_THROUGHOUT:
            # No clear border (a dark menu hides it), but a small steady face in a corner for the whole clip is a cam all the same, unless a far
            # bigger face is the picture. Its rectangle is sized from the face, and the page swaps in a border-found one from another clip of the stream.
            cam, guessed = webcam_rect(face), True
            if remembered and inside(face, remembered):
                # The stream's cam is known from another clip and this face sits in it: that is the rectangle, border or no border.
                cam, guessed = remembered, False
        if cam:
            framed.append((face, person, cam, guessed))
    if framed:
        # When more than one face could be the cam: the one in view for more of the clip, then the one with the cleaner border, then the smaller
        # frame, since a webcam is an inset and a panel a quarter of the screen wide is the picture itself.
        rank = lambda f: (round(f[1]["frames"] / len(looks), 1), round(strength(pictures, f[2]), 2), -f[2]["w"] * f[2]["h"])
        face, person, cam, guessed = max(framed, key=rank)
        return {"layout": "webcam", "faces": [{k: face[k] for k in "xywh"}], "webcam": cam, "guessed": guessed,
                "share": round(person["frames"] / len(looks), 3), "reason": "A webcam sits over the picture" if not guessed else "A webcam sits in a corner of the picture"}
    if holds(pictures, remembered):
        # No face framed a cam, but the stream's cam still shows its border: the streamer has leaned out of it, and the lane shows the cam all the same.
        return recalled(remembered, faces)
    equals = [f for f in faces if f["w"] >= big["w"] * SIMILAR]
    if len(equals) >= 2:
        picked = reading_order(equals[:MAX_PEOPLE])
        return {"layout": "people", "faces": [{k: f[k] for k in "xywh"} for f in picked], "webcam": None,
                "reason": f"{len(picked)} people share the frame"}
    if is_webcam(big, seen[0]):
        known = remembered and inside(big, remembered)
        return {"layout": "webcam", "faces": [{k: big[k] for k in "xywh"}], "webcam": remembered if known else webcam_rect(big),
                "reason": "A webcam sits in a corner of the picture"}
    return {"layout": "single", "faces": [{k: big[k] for k in "xywh"}], "webcam": None, "reason": "One person fills the picture"}


def medians(grays):
    """The clip's middle picture in gray, as the whole clip and as each of a few interleaved thirds of its looks.

    What stays put (a webcam's border) holds in all of them, while a stray edge shows up in only some; border() averages
    the evidence over the set.
    """
    if not grays:
        return None
    pick = [grays] + ([grays[k::SUBSETS] for k in range(SUBSETS)] if len(grays) >= SUBSETS * 3 else [])
    return [np.median(np.stack(g), axis=0).astype(np.float32) for g in pick]


def same_picture(a, b):
    """Whether two shots call for the same layout in the same place, so one crop serves both."""
    if a["layout"] != b["layout"]:
        return False
    if a["layout"] == "webcam":
        # The crop is the cam itself, whether or not anyone is in it.
        return all(abs(a["webcam"][k] - b["webcam"][k]) <= SAME_CAM for k in ("x", "y", "w", "h"))
    close = lambda p, q: abs(p["x"] - q["x"]) <= SAME_SPOT and abs(p["y"] - q["y"]) <= SAME_SPOT
    return len(a["faces"]) == len(b["faces"]) and all(close(p, q) for p, q in zip(a["faces"], b["faces"]))


def merge_segments(shots, end):
    """Join neighbouring shots that want the same crop, and fold shots too short to matter into the one before.

    `shots` are decisions with a start time; returns segments with start and end, the first starting where the clip does.
    """
    merged = []
    for shot in shots:
        if merged and (same_picture(merged[-1], shot)):
            continue
        merged.append(shot)
    ends = [m["start"] for m in merged[1:]] + [end]
    spans = [{**m, "end": e} for m, e in zip(merged, ends)]
    out = []
    for span in spans:
        if out and span["end"] - span["start"] < MIN_SEGMENT:
            out[-1] = {**out[-1], "end": span["end"]}
        else:
            out.append(span)
    if len(out) > 1 and out[0]["end"] - out[0]["start"] < MIN_SEGMENT:
        out = [{**out[1], "start": out[0]["start"]}] + out[2:]
    joined = []
    for span in out:
        if joined and same_picture(joined[-1], span):
            joined[-1] = {**joined[-1], "end": span["end"]}
        else:
            joined.append(span)
    return joined


def keep_webcam(shots, ranges, looks):
    """A webcam does not leave when the game cuts: a shot that has no clear border of its own still gets the webcam of the
    longest shot that does, while that webcam's face is in the same place for most of it."""
    cams = [i for i, s in enumerate(shots) if s["layout"] == "webcam"]
    if not cams:
        return shots
    anchor = max(cams, key=lambda i: ranges[i][1] - ranges[i][0])
    if not shots[anchor]["faces"]:
        # A remembered cam with nobody in it was checked shot by shot on its border; there is no face to carry it to the other shots on.
        return shots
    face = shots[anchor]["faces"][0]
    out = []
    for i, shot in enumerate(shots):
        first, last = ranges[i]
        near = sum(any(abs(x + w / 2 - face["x"]) <= SAME_SPOT and abs(y + h / 2 - face["y"]) <= SAME_SPOT for x, y, w, h in looks[n])
                   for n in range(first, last))
        keep = shot["layout"] != "webcam" and last > first and near >= (last - first) / 2
        out.append({**shots[anchor], "start": shot["start"]} if keep else shot)
    return out


def analyze(src, start, end, frames=None, detector=None, is_cut=None, remembered=None):
    """Look at a clip and say which layout suits it, shot by shot.

    Returns {"layout", "faces", "webcam", "reason", "segments"}: the top-level fields describe the longest segment, and each
    segment ({start, end, layout, faces, webcam, reason}, times in the source) is one stretch that wants one crop. Faces are
    fractions of the frame (x and y are the centre), in reading order for people; webcam is the likely rectangle of a facecam.
    `remembered` is the cam found in another clip of the same stream, used when this clip shows its border but no face frames it.
    """
    if not 0 <= start < end or end - start > MAX_SPAN:
        raise ValueError(f"Pick a clip under {MAX_SPAN:g} seconds")
    import cv2
    if frames is None:
        from person_follow import read_frames
        from reframe import probe_size
        w, h = probe_size(src)
        frames = read_frames(src, start, end, FPS, WIDTH)
        detector = detector or yunet(WIDTH, max(2, round(h * WIDTH / w / 2) * 2))
    if is_cut is None:
        from person_follow import is_cut
    frames = list(frames)
    if frames and frames[0][1].shape[0] > frames[0][1].shape[1]:
        # A video shot vertical already fits a Short as it is; cropping it to a face would throw away the picture it was framed for.
        whole = {"layout": "none", "faces": [], "webcam": None, "reason": "Already vertical, so the picture stays whole"}
        return {**whole, "segments": [{**whole, "start": round(start, 2), "end": round(end, 2)}]}
    times, looks, grays, firsts, prev = [], [], [], [], None
    for t, frame in frames:
        fh, fw = frame.shape[:2]
        if prev is None or is_cut(prev, frame):
            firsts.append(len(times))
        prev = frame
        times.append(round(t, 2))
        grays.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        looks.append([(x / fw, y / fh, w / fw, h / fh) for x, y, w, h in (f["box"] for f in detect_faces(detector, frame))])
    if not times:
        return {**decide([]), "segments": []}
    looked = grays[:: max(1, len(grays) // MAX_LOOKS)]
    whole = decide(looks, medians(looked), looked, remembered)
    if whole["layout"] == "webcam" and whole.get("share", 1.0) >= CAM_THROUGHOUT:
        # A webcam stays put through the game's own cuts, so one answer serves the whole clip.
        return {**whole, "segments": [{**whole, "start": round(start, 2), "end": round(end, 2)}]}
    shots, ranges = [], []
    for k, first in enumerate(firsts):
        last = firsts[k + 1] if k + 1 < len(firsts) else len(times)
        ranges.append((first, last))
        stride = max(1, (last - first) // MAX_LOOKS)
        # A webcam stays put through the cuts, so the whole clip shows it too. A border found in only some shots is the picture's own edge.
        shot = grays[first:last:stride] if whole["layout"] == "webcam" else None
        shots.append({**decide(looks[first:last], medians(shot), shot, remembered), "start": start if k == 0 else times[first]})
    segments = merge_segments(keep_webcam(shots, ranges, looks), end)
    longest = max(segments, key=lambda s: s["end"] - s["start"])
    keys = ("layout", "faces", "webcam", "reason", "guessed", "remembered")
    return {**{k: longest[k] for k in keys if k in longest}, "segments": [{**seg, "start": round(seg["start"], 2), "end": round(seg["end"], 2)} for seg in segments]}
