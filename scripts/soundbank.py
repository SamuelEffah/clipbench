"""Browse and import sounds from soundbuttonsworld.com. Only the three documented endpoints are used, and only
file names in the shape the site issues are ever fetched."""
import json
import re
import subprocess
import urllib.parse

API = "https://soundbuttonsworld.com/api"
PAGE_SIZE = 40
MAX_SOUND_BYTES = 25 * 1024 ** 2
FILE_NAME = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.mp3")
TIMEOUT = 20


def _get(url):
    """The body at a URL, through curl because the Python that ships with macOS can't verify certificates."""
    try:
        run = subprocess.run(["curl", "-sfL", "--max-time", str(TIMEOUT), "--max-filesize", str(MAX_SOUND_BYTES), url],
                             capture_output=True, check=True)
    except subprocess.CalledProcessError as err:
        raise OSError(f"the library answered with an error (curl {err.returncode})") from err
    return run.stdout


def browse(query="", page=1):
    """One page of sounds, newest first, or matches for the query. Returns {total, sounds: [{id, name, file}]}."""
    page = max(1, int(page))
    params = {"page": page, "pageSize": PAGE_SIZE}
    if query.strip():
        url = f"{API}/memes/search?{urllib.parse.urlencode({**params, 'q': query.strip()})}"
    else:
        url = f"{API}/memes/new?{urllib.parse.urlencode(params)}"
    data = json.loads(_get(url))
    sounds = [{"id": s["id"], "name": str(s.get("name", "")).strip().title() or "Sound", "file": s["fileName"]}
              for s in data.get("data", []) if isinstance(s, dict) and FILE_NAME.fullmatch(str(s.get("fileName", "")))]
    return {"total": int(data.get("total", len(sounds))), "page": page, "pageSize": PAGE_SIZE, "sounds": sounds}


def download_url(file_name):
    return f"{API}/upload/download?{urllib.parse.urlencode({'id': file_name})}"


def fetch(file_name):
    """The bytes of one sound. Raises ValueError for a name the site would not have issued."""
    if not FILE_NAME.fullmatch(file_name or ""):
        raise ValueError("That isn't a sound from the library")
    data = _get(download_url(file_name))
    if not data or len(data) > MAX_SOUND_BYTES:
        raise ValueError("The sound was empty or too large")
    return data
