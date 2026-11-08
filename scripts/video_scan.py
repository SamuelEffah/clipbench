"""Hard cuts and picture motion from one decode of a video.

Scene cuts and motion each need every frame, and decoding a long episode is the slow part, so ffmpeg decodes once
and feeds both measurements."""
import re
import subprocess
import threading

import clip_motion

TIME_RE = re.compile(r"pts_time:(\d+(?:\.\d+)?)")


def graph(threshold, per_sec):
    """Split one decode into a scene-cut branch (a small copy, only cuts kept) and a motion branch (tiny gray frames)."""
    return (f"[0:v]split=2[a][b];"
            f"[a]scale=320:-2,select='gt(scene,{threshold})',showinfo[s];"
            f"[b]fps={per_sec},scale={clip_motion.WIDTH}:{clip_motion.HEIGHT},format=gray[m]")


def cut_times(log, min_gap):
    times = []
    for m in TIME_RE.finditer(log):
        t = float(m.group(1))
        if not times or t - times[-1] >= min_gap:
            times.append(round(t, 2))
    return times


def scan(src, threshold, min_gap, per_sec=clip_motion.PER_SEC):
    """(scene cut times, motion) for a video, each None when it could not be read: motion is {per_sec, values}."""
    cmd = ["ffmpeg", "-v", "info", "-nostats", "-i", str(src), "-an", "-sn", "-filter_complex", graph(threshold, per_sec),
           "-map", "[s]", "-fps_mode", "passthrough", "-f", "null", "-",
           "-map", "[m]", "-f", "rawvideo", "-"]
    log = []
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace") as proc:
        # showinfo writes to stderr while the motion frames fill stdout, so both are drained at once.
        reader = threading.Thread(target=lambda: log.append(proc.stderr.read()), daemon=True)
        reader.start()
        values = clip_motion.from_frames(clip_motion._frames(proc.stdout.buffer))
        reader.join()
        failed = proc.wait() != 0
    if failed:
        return None, None
    return cut_times("".join(log), min_gap), {"per_sec": per_sec, "values": values}
