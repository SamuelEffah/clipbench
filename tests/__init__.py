import os
import sys
from pathlib import Path

os.environ.setdefault("CLIPBENCH_NO_WARM", "1")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import ffmpeg_env  # noqa: E402

# Render tests burn captions and titles, so they need the same FFmpeg the app picks.
ffmpeg_env.activate()
