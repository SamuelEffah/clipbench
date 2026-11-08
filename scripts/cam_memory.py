"""Where a stream keeps its webcam, remembered from one clip for the next.

A streamer's cam does not move between clips of one stream, and a stream is often recorded as one file per stretch, named alike
with a different time at the end. The cam found from its border in one of them serves the others, including a clip where the
streamer has leaned out of the cam and no face is there to find it from.
"""
import json
import re
from pathlib import Path

TRAIL = re.compile(r"-(\d{4,}|[\w-]{11})$")  # a recording's time, or a video site's id, at the end of a file name


def stream_key(src):
    """The name a stream's recordings share: the file name without its folder, extension and trailing time or id.

    The trailing part comes off only when what is left is at least as long, so a name that is little more than a number
    (a live recording's `rec-1762500000`) stays its own key rather than every recording sharing one.
    """
    stem = Path(str(src)).stem
    trail = TRAIL.search(stem)
    title = stem[:trail.start()] if trail and trail.start() >= len(trail.group(1)) else stem
    return title.casefold()


class CamMemory:
    def __init__(self, path):
        self.path = Path(path)

    def _load(self):
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def recall(self, src, width, height):
        """The cam remembered for this stream at this picture size, or None."""
        entry = self._load().get(stream_key(src))
        if not isinstance(entry, dict) or entry.get("width") != width or entry.get("height") != height:
            return None
        cam = entry.get("webcam")
        return cam if isinstance(cam, dict) and all(isinstance(cam.get(k), (int, float)) for k in "xywh") else None

    def remember(self, src, width, height, webcam):
        """Keep this cam for the stream, replacing any earlier one. Raises OSError when the file cannot be written."""
        entry = {"webcam": {k: webcam[k] for k in "xywh"}, "width": width, "height": height, "src": str(src)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({**self._load(), stream_key(src): entry}))
