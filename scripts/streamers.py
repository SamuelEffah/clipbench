"""The YouTube and Twitch channels you watch for going live: a saved list, and a check of whether one is live right now."""
import json
import re
import subprocess
from pathlib import Path

CHECK_TIMEOUT = 40
HANDLE = re.compile(r"@([\w.-]{1,60})")
CHANNEL_ID = re.compile(r"/channel/(UC[\w-]{10,40})")
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
TWITCH_HOSTS = {"twitch.tv", "www.twitch.tv", "m.twitch.tv"}
TWITCH_LOGIN = re.compile(r"/([A-Za-z0-9_]{2,25})(?:/|$)")
# Twitch pages that sit where a channel name would.
TWITCH_PAGES = {"videos", "directory", "downloads", "jobs", "settings", "turbo", "store", "subs", "friends", "wallet", "search", "clips", "popout", "embed", "p", "u"}
SAVED_CHANNEL = re.compile(r"https://www\.youtube\.com/(?:@[\w.-]{1,60}|channel/UC[\w-]{10,40})|https://www\.twitch\.tv/[a-z0-9_]{2,25}")
ASK = "Paste a YouTube channel link or @handle, or a twitch.tv link"


def normalize(text):
    """The channel a handle or a YouTube link points to, as {name, url}. Raises ValueError for anything else."""
    text = str(text).strip()
    if not text or re.search(r"\s", text):
        raise ValueError(ASK)
    if "/" not in text and "." not in text:
        text = "@" + text.lstrip("@")
    if text.startswith("@"):
        found = HANDLE.fullmatch(text)
        if not found:
            raise ValueError("That isn't a channel handle")
        return {"name": found.group(1), "url": f"https://www.youtube.com/@{found.group(1)}"}
    bare = re.sub(r"^https?://", "", text)
    host, _, rest = bare.partition("/")
    path = "/" + re.split(r"[?#]", rest)[0]
    if host.lower() in TWITCH_HOSTS:
        found = TWITCH_LOGIN.match(path)
        if not found or found.group(1).lower() in TWITCH_PAGES:
            raise ValueError("That link isn't a Twitch channel. Use the channel page, like twitch.tv/name")
        login = found.group(1)
        return {"name": login, "url": f"https://www.twitch.tv/{login.lower()}"}
    if host.lower() not in YOUTUBE_HOSTS:
        raise ValueError(ASK)
    if found := re.match(r"/@([\w.-]{1,60})", path):
        return {"name": found.group(1), "url": f"https://www.youtube.com/@{found.group(1)}"}
    if found := CHANNEL_ID.match(path):
        return {"name": found.group(1), "url": f"https://www.youtube.com/channel/{found.group(1)}"}
    raise ValueError("That link isn't a YouTube channel. Use the channel page, like youtube.com/@name")


def kind_of(url):
    return "twitch" if "twitch.tv/" in url else "youtube"


def load(path):
    try:
        saved = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(saved, list):
        return []
    return [{"name": str(s.get("name", ""))[:80], "url": s["url"], "kind": kind_of(s["url"])}
            for s in saved if isinstance(s, dict) and isinstance(s.get("url"), str) and SAVED_CHANNEL.fullmatch(s["url"])]


def _write(path, items):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(items))
    return items


def add(path, text):
    """The list with this channel added, unless it is already there (handles are not case sensitive)."""
    found, current = normalize(text), load(path)
    if any(s["url"].lower() == found["url"].lower() for s in current):
        return current
    _write(path, [*current, found])
    return load(path)


def remove(path, url):
    _write(path, [s for s in load(path) if s["url"].lower() != str(url).lower()])
    return load(path)


def check_live(exe, url):
    """{live: True, title, watch} when the channel is streaming now, {live: False} when it is not.
    Raises ValueError when the site could not be asked, so a bad network never shows as offline."""
    twitch = kind_of(url) == "twitch"
    # YouTube's /live page is the channel's current stream. Twitch's channel page is, and its title field is only "name (live)".
    fields, page = ("%(is_live)s|%(id)s|%(description).200s", url) if twitch else ("%(is_live)s|%(id)s|%(title)s", url + "/live")
    try:
        got = subprocess.run([exe, "--no-warnings", "--no-playlist", "--skip-download", "--print", fields, "--", page],
                             capture_output=True, text=True, timeout=CHECK_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        raise ValueError("Couldn't check this channel")
    if got.returncode:
        if "not currently live" in got.stderr:
            return {"live": False}
        raise ValueError("Couldn't check this channel")
    live, _, rest = got.stdout.strip().partition("|")
    video, _, title = rest.partition("|")
    if live != "True" or not re.fullmatch(r"[\w-]{6,20}", video):
        return {"live": False}
    watch = url if twitch else f"https://www.youtube.com/watch?v={video}"
    return {"live": True, "title": title.splitlines()[0][:200] if title.strip() else "", "watch": watch}
