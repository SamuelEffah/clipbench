"""Keyframes that make a zoomed-in crop follow a face over time.

A track is a list of (t, zx, zy): at t seconds into the clip's source stretch the crop's centre is at (zx, zy), each 0 to 1.
Positions between keyframes are straight lines, and before the first or after the last they hold still.
"""
import statistics

MAX_KEYS = 120
MAX_SPEED = 0.12  # fastest the face may appear to move, in frame widths per second, so the crop never whips
FOLLOW_SPEED = 0.4  # a drawn subject may move faster than a face before the crop lags it
TREMOR = 0.01  # a wobble smaller than this, in frame widths, is not a move: keyframes it needs are dropped


def smooth(samples, window=5, max_speed=MAX_SPEED):
    """Calm raw face detections ({t, x, y}) into a track: a rolling median drops stray hits, then the speed is capped."""
    ordered = sorted(samples, key=lambda s: s["t"])
    half = window // 2
    out = []
    for i, s in enumerate(ordered):
        near = ordered[max(0, i - half): i + half + 1]
        x, y = statistics.median(n["x"] for n in near), statistics.median(n["y"] for n in near)
        if out:
            dt = max(s["t"] - out[-1]["t"], 1e-6)
            room = max_speed * dt
            x = out[-1]["x"] + max(-room, min(room, x - out[-1]["x"]))
            y = out[-1]["y"] + max(-room, min(room, y - out[-1]["y"]))
        out.append({"t": s["t"], "x": round(x, 4), "y": round(y, 4)})
    return out


def _off(p, a, b):
    """How far p is from the straight line a to b, at p's own time, in the larger of x and y."""
    span = b["t"] - a["t"]
    f = (p["t"] - a["t"]) / span if span > 0 else 1.0
    return max(abs(p["x"] - (a["x"] + (b["x"] - a["x"]) * f)), abs(p["y"] - (a["y"] + (b["y"] - a["y"]) * f)))


def _keep(path, tolerance):
    """The points of a path ({t, x, y}, by time) that a straight line between neighbours would miss by more than the tolerance."""
    keep = {0, len(path) - 1}
    todo = [(0, len(path) - 1)]
    while todo:
        lo, hi = todo.pop()
        if hi - lo < 2:
            continue
        far, worst = max(((i, _off(path[i], path[lo], path[hi])) for i in range(lo + 1, hi)), key=lambda r: r[1])
        if worst > tolerance:
            keep.add(far)
            todo += [(lo, far), (far, hi)]
    return [path[i] for i in sorted(keep)]


def simplify(samples, tolerance=TREMOR, max_keys=MAX_KEYS):
    """A face's raw positions cut down to the keyframes that matter. Tremor between them is dropped, so the crop does not shake,
    and a jump at a cut or a change of speaker is kept. A path that still has too many keyframes is loosened until it fits."""
    path = sorted(samples, key=lambda s: s["t"])
    if len(path) < 3:
        return path
    kept = _keep(path, tolerance)
    while len(kept) > max_keys:
        tolerance *= 1.5
        kept = _keep(path, tolerance)
    return kept


def parse_track(text):
    """Keyframes from 't:zx:zy,t:zx:zy' as a sorted list of (t, zx, zy). Raises ValueError for anything off."""
    keys = []
    for part in str(text).split(","):
        if not part.strip():
            continue
        try:
            t, zx, zy = (float(v) for v in part.split(":"))
        except ValueError:
            raise ValueError(f"bad track keyframe '{part.strip()}' (want t:zx:zy)") from None
        if t < 0 or not (0 <= zx <= 1 and 0 <= zy <= 1):
            raise ValueError(f"track keyframe '{part.strip()}' is out of range")
        keys.append((t, zx, zy))
    if len(keys) > MAX_KEYS:
        raise ValueError(f"a track can have at most {MAX_KEYS} keyframes")
    return sorted(keys)


def format_track(keys):
    return ",".join(f"{t:.2f}:{zx:.3f}:{zy:.3f}" for t, zx, zy in keys)


def at(keys, t):
    """The (zx, zy) of a track at time t."""
    if not keys:
        raise ValueError("an empty track has no position")
    if t <= keys[0][0]:
        return keys[0][1], keys[0][2]
    for (t0, x0, y0), (t1, x1, y1) in zip(keys, keys[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 1.0
            return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f
    return keys[-1][1], keys[-1][2]


def to_output_time(keys, start, pieces):
    """Re-time keyframes from seconds into the source stretch to seconds into the finished clip.

    `pieces` are (source start, source end, speed) per stretch, as the renderer cuts them; `start` is the cut's source start.
    """
    def out(rel):
        s, acc = start + rel, 0.0
        for a, b, speed in pieces:
            if s <= a:
                break
            acc += (min(s, b) - a) / speed
        return acc
    retimed = [(out(t), zx, zy) for t, zx, zy in keys]
    return [k for i, k in enumerate(retimed) if i == 0 or k[0] > retimed[i - 1][0]]


def expression(keys, axis):
    """An ffmpeg expression in t for one axis (1 = zx, 2 = zy) of a track already in output time."""
    values = [(k[0], k[axis]) for k in keys]
    expr = f"{values[-1][1]:.4f}"
    for (t0, v0), (t1, v1) in reversed(list(zip(values, values[1:]))):
        slope = (v1 - v0) / (t1 - t0)
        expr = f"if(lt(t,{t1:.3f}),{v0:.4f}+({slope:.5f})*(t-{t0:.3f}),{expr})"
    return f"if(lt(t,{values[0][0]:.3f}),{values[0][1]:.4f},{expr})"
