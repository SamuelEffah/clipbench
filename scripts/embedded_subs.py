"""Captions that come with a downloaded video: the English subtitle track inside it, or a .srt/.vtt saved beside it.
They are the real lines of the show, so they beat listening for them."""
import functools
import json
import re
import subprocess
from pathlib import Path

MAX_WORDS = 400
SIDECAR = (".srt", ".vtt")
SOUND_NOTE = re.compile(r"^\s*[\[(♪].*[\])♪]\s*$")
CUE = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})")
ENGLISH = ("eng", "en")
DRAWING = re.compile(r"^m\s+-?[\d.]+\s+-?[\d.]+\s+l\s[-\d.\sa-z]*$")
JOIN_GAP = 0.25


def seconds(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def tidy(found):
    """Subtitle lines in order, minus what typeset tracks add: drawing commands, doubled layers, and a line that fades or
    moves as one cue per frame, which is joined back into a single line."""
    out, latest = [], {}
    for a, b, text in sorted(set(found)):
        if DRAWING.match(text):
            continue
        # Sorted starts mean only the latest occurrence can still join this line.
        # Looking it up avoids scanning the whole track for every unique line.
        n = latest.get(text)
        if n is not None and a <= out[n][1] + JOIN_GAP:
            out[n] = (out[n][0], max(out[n][1], b), text)
        else:
            latest[text] = len(out)
            out.append((a, b, text))
    return out


@functools.lru_cache(maxsize=64)
def english_stream(src):
    """The index of the best English subtitle stream in the file, or None. Full dialogue wins over closed captions,
    which add sound notes, and over a forced track, which only carries signs."""
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries", "stream=index:stream_tags=language,title",
                            "-of", "json", src], capture_output=True, text=True)
    try:
        streams = json.loads(probe.stdout or "{}").get("streams", [])
    except ValueError:
        return None

    def rank(stream):
        title = (stream.get("tags", {}).get("title") or "").lower()
        return ("forced" in title or "sign" in title, "cc" in title.split() or "sdh" in title)

    english = [s for s in streams if (s.get("tags", {}).get("language") or "").lower() in ENGLISH]
    return min(english, key=rank)["index"] if english else None


def sidecar(src):
    stem = Path(src).stem
    for path in sorted(Path(src).parent.glob(f"{stem}*")):
        if path.suffix.lower() in SIDECAR and re.search(r"\.(en|eng)(\.|$)", path.name[len(stem):], re.I):
            return str(path)
    return None


@functools.lru_cache(maxsize=16)
def all_cues(src):
    """[(from, to, text)] for every line of the English subtitles, in seconds from the video's start.
    None when there are none. ffmpeg's -ss is unreliable on subtitle streams, so ranges are cut here instead."""
    stream, side = english_stream(src), None
    if stream is None:
        side = sidecar(src)
        if side is None:
            return None
    cmd = ["ffmpeg", "-v", "error", "-i", side or src, "-map", "0:s:0" if side else f"0:{stream}", "-f", "srt", "-"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        return None
    found = []
    for block in re.split(r"\n\s*\n", out.stdout.replace("\r", "")):
        lines = [ln for ln in block.strip().split("\n") if ln.strip()]
        at = next((n for n, ln in enumerate(lines) if "-->" in ln), None)
        timing = CUE.search(lines[at]) if at is not None else None
        if not timing:
            continue
        g = timing.groups()
        text = " ".join(re.sub(r"<[^>]+>|\{[^}]*\}", "", " ".join(lines[at + 1:])).split())
        a, b = seconds(*g[:4]), seconds(*g[4:])
        if text and b > a and not SOUND_NOTE.match(text):
            found.append((a, b, text))
    return tidy(found)


def cues(src, start, end):
    """The lines that overlap the range, as (from, to, text) in seconds from `start`; a line may begin before 0 or end past the range. None when there are no subtitles."""
    every = all_cues(src)
    if every is None:
        return None
    out = []
    # tidy() preserves ascending starts, even when subtitle layers overlap.
    # Once a cue starts past the clip, the remaining track cannot contribute.
    for a, b, text in every:
        if a >= end:
            break
        if b > start:
            out.append((a - start, b - start, text))
    return out


def words(src, start, end):
    """Timed words [text, from, to] for a stretch of a video, laid evenly along each subtitle line.
    None when the video carries no English subtitles; [] when it does but nothing is said in the range."""
    lines = cues(src, start, end)
    if lines is None:
        return None
    out, length = [], end - start
    for a, b, text in lines:
        parts = text.split()
        step = (b - a) / len(parts)
        for n, w in enumerate(parts):
            lo, hi = a + n * step, a + (n + 1) * step
            if hi > 0 and lo < length:
                out.append([w[:40], round(max(lo, 0.0), 2), round(min(hi, length), 2)])
                if len(out) >= MAX_WORDS:
                    return out
    return out


def has_subtitles(src):
    return english_stream(src) is not None or sidecar(src) is not None
