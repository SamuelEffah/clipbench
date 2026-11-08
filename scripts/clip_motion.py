"""How much the picture moves, second by second, so clips can be ranked on what happens and not only on what is heard.

Tiny grayscale frames are sampled from the video and each is compared with the one before. A hard cut
reads as the largest change, which is capped, so it does not set the scale for everything else."""
import subprocess

PER_SEC = 4
WIDTH, HEIGHT = 32, 18
# A mean change of this many levels out of 255 between two sampled frames counts as full motion.
FULL_CHANGE = 30


def from_frames(frames):
    """0 to 255 for each step between two neighbouring frames (bytes of WIDTH * HEIGHT grays)."""
    out, prev = [], None
    for cur in frames:
        if prev is not None:
            change = sum(abs(a - b) for a, b in zip(prev, cur)) / len(cur)
            out.append(min(255, round(change * 255 / FULL_CHANGE)))
        prev = cur
    return out


def _frames(stream):
    size = WIDTH * HEIGHT
    while len(chunk := stream.read(size)) == size:
        yield chunk


def compute(src, per_sec=PER_SEC):
    """{per_sec, values}: the motion of a video, per_sec samples a second. No values when it cannot be read."""
    cmd = ["ffmpeg", "-v", "error", "-i", str(src), "-an", "-sn", "-vf",
           f"fps={per_sec},scale={WIDTH}:{HEIGHT},format=gray", "-f", "rawvideo", "-"]
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        values = from_frames(_frames(proc.stdout))
        failed = proc.wait() != 0
    return {"per_sec": per_sec, "values": [] if failed else values}
