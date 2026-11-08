"""Upload a rendered Short to YouTube: OAuth for a Desktop-app client, then a resumable upload.

All HTTPS goes through the system curl. Python's own TLS stack fails on this Mac (a TLS-inspecting
tool breaks certificate checks), and curl uses the system keychain, so it works. Secrets are handed to
curl on stdin as a config file, never on the command line where `ps` could show them.

Every upload goes up unlisted, with the made-for-kids and altered-content questions answered and the description's
hashtags as tags, so nothing is left to fill in. The Short is made public in YouTube Studio when the time is right.
YouTube may keep an upload private until the API project has passed its audit; what it actually did is reported back.
"""
import base64
import hashlib
import json
import re
import secrets
import subprocess
import threading
import time
from collections import namedtuple
from pathlib import Path
from urllib.parse import urlencode

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
REPORTS_ENDPOINT = "https://youtubeanalytics.googleapis.com/v2/reports"
CHANNELS_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels"
PLAYLIST_ITEMS_ENDPOINT = "https://www.googleapis.com/youtube/v3/playlistItems"
PAGE_SIZE = 50
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"  # view counts of the channel's videos
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"  # how much of each video was watched
SCOPE = f"{UPLOAD_SCOPE} {READ_SCOPE} {ANALYTICS_SCOPE}"
RETENTION_METRICS = "views,averageViewDuration,averageViewPercentage"
STATS_BATCH = 50  # the most video ids one statistics request takes
TOKEN_KEY = "youtube_tokens"
CHANNEL_KEY = "youtube_channel"  # the connected channel's name and handle, as channel_identity returns them
CLIENT_FILE_HINT = "workspace/data/youtube_client.json"
TITLE_LIMIT = 100
DESCRIPTION_LIMIT = 5000
CATEGORY_ENTERTAINMENT = "24"
EXPIRY_MARGIN = 60
HTTP_MARK = "\n__HTTP__"

CurlResult = namedtuple("CurlResult", "code stdout stderr")
Uploaded = namedtuple("Uploaded", "video_id privacy")  # the new video and the privacy YouTube actually gave it
UPLOAD_PRIVACY = "unlisted"
MAX_TAGS = 30
TAGS_CHARS = 500  # YouTube's room for all tags together, each counted with its quotes
HASHTAG = re.compile(r"#(\w+)")


class YouTubeError(Exception):
    pass


class YouTubeAuthError(YouTubeError):
    """The saved sign-in is missing or no longer valid; connect again."""


class YouTubeScopeError(YouTubeError):
    """The sign-in predates the read permission, so it can still upload but not read counts; connect again to add it."""


def config_value(text):
    escaped = str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{escaped}"'


def last_percent(text):
    hits = re.findall(r"(\d+(?:\.\d+)?)%", text)
    return float(hits[-1]) if hits else None


def studio_url(video_id):
    return f"https://studio.youtube.com/video/{video_id}/edit"


def curl_run(args, stdin=None, on_stderr=None):
    proc = subprocess.Popen(["curl", *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = []
    reader = threading.Thread(target=lambda: out.append(proc.stdout.read()), daemon=True)
    reader.start()
    if stdin is not None:
        proc.stdin.write(stdin.encode())
    proc.stdin.close()
    err = b""
    while chunk := proc.stderr.read(256):
        err += chunk
        if on_stderr:
            on_stderr(chunk.decode("utf-8", "replace"))
    proc.wait()
    reader.join()
    return CurlResult(proc.returncode, (out[0] if out else b"").decode("utf-8", "replace"), err.decode("utf-8", "replace"))


def load_client(path):
    try:
        data = json.loads(Path(path).read_text())
    except OSError:
        raise YouTubeError(f"Google sign-in isn't set up yet. Save the OAuth client file as {CLIENT_FILE_HINT}.")
    except ValueError:
        raise YouTubeError(f"{CLIENT_FILE_HINT} isn't valid JSON. Download the client file from Google Cloud again.")
    if not isinstance(data, dict):
        raise YouTubeError(f"{CLIENT_FILE_HINT} isn't an OAuth client file.")
    if "installed" not in data:
        raise YouTubeError("That OAuth client isn't the Desktop app type. Create a new client in Google Cloud and choose Desktop app.")
    client = data["installed"]
    if not isinstance(client, dict) or not client.get("client_id") or not client.get("client_secret"):
        raise YouTubeError(f"{CLIENT_FILE_HINT} is missing the client id or secret.")
    return {"client_id": client["client_id"], "client_secret": client["client_secret"]}


def new_pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def auth_url(client, redirect_uri, state, challenge):
    return AUTH_ENDPOINT + "?" + urlencode({
        "client_id": client["client_id"], "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPE,
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        "access_type": "offline", "prompt": "consent",
    })


def _post_form(fields, run):
    config = f"url = {config_value(TOKEN_ENDPOINT)}\nrequest = \"POST\"\n" + "".join(
        f"data-urlencode = {config_value(f'{k}={v}')}\n" for k, v in fields.items())
    res = run(["--silent", "--show-error", "--connect-timeout", "20", "--config", "-"], config)
    if res.code != 0:
        raise YouTubeError(f"Couldn't reach Google: {_last_line(res.stderr)}")
    try:
        data = json.loads(res.stdout)
    except ValueError:
        raise YouTubeError("Google sent back something unexpected")
    if "error" in data:
        message = data.get("error_description") or str(data["error"])
        raise (YouTubeAuthError if data["error"] == "invalid_grant" else YouTubeError)(message)
    return data


def _last_line(text):
    lines = [ln.strip() for ln in text.replace("\r", "\n").split("\n") if ln.strip()]
    return lines[-1] if lines else "no details"


def exchange_code(client, code, verifier, redirect_uri, run=curl_run, now=None):
    data = _post_form({"code": code, "client_id": client["client_id"], "client_secret": client["client_secret"],
                       "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier}, run)
    if not data.get("access_token") or not data.get("refresh_token"):
        raise YouTubeError("Google didn't return a long-lived sign-in. Remove the app's access in your Google account and connect again.")
    return {"access_token": data["access_token"], "refresh_token": data["refresh_token"], "scope": str(data.get("scope") or SCOPE),
            "expires_at": (now if now is not None else time.time()) + int(data.get("expires_in", 3600))}


def _granted(tokens, scope):
    return scope in str((tokens or {}).get("scope") or "").split()


def can_read(tokens):
    """Whether a saved sign-in was granted the read permission. Sign-ins from before it was asked for carry no scope."""
    return _granted(tokens, READ_SCOPE)


def can_analyze(tokens):
    """Whether a saved sign-in was granted the analytics permission."""
    return _granted(tokens, ANALYTICS_SCOPE)


def access_token(store, client, run=curl_run, now=None):
    now = now if now is not None else time.time()
    tokens = store.get_setting(TOKEN_KEY)
    if not tokens or not tokens.get("refresh_token"):
        raise YouTubeAuthError("Connect YouTube first")
    if tokens.get("expires_at", 0) - EXPIRY_MARGIN > now:
        return tokens["access_token"]
    try:
        data = _post_form({"client_id": client["client_id"], "client_secret": client["client_secret"],
                           "refresh_token": tokens["refresh_token"], "grant_type": "refresh_token"}, run)
    except YouTubeAuthError:
        store.delete_setting(TOKEN_KEY)
        raise YouTubeAuthError("YouTube access ended. Connect again.")
    store.set_setting(TOKEN_KEY, {**tokens, "access_token": data["access_token"],
                                  "expires_at": now + int(data.get("expires_in", 3600))})
    return data["access_token"]


def _friendly(status, body):
    try:
        err = json.loads(body).get("error", {})
    except (ValueError, AttributeError):
        err = {}
    reasons = {e.get("reason") for e in err.get("errors", []) if isinstance(e, dict)} if isinstance(err, dict) else set()
    if reasons & {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}:
        return "YouTube's daily upload quota for this app is used up. Try again tomorrow."
    if "uploadLimitExceeded" in reasons:
        return "This channel has reached YouTube's upload limit. Try again later."
    if "forbidden" in reasons or status == 403:
        return "YouTube refused the upload. Check the channel can upload videos and that the YouTube Data API is enabled."
    message = err.get("message") if isinstance(err, dict) else None
    return message or f"YouTube returned an error ({status})"


def _count(stats, key):
    try:
        return int(stats[key])
    except (KeyError, TypeError, ValueError):
        return None


def _get_json(token, url, run, scope_error):
    """GET a Google API URL as the signed-in channel. 401 and a refused permission become the matching errors."""
    config = f"url = {config_value(url)}\nheader = {config_value('Authorization: Bearer ' + token)}\n"
    res = run(["--silent", "--show-error", "--connect-timeout", "20", "-w", HTTP_MARK + "%{http_code}", "--config", "-"], config)
    if res.code != 0:
        raise YouTubeError(f"Couldn't reach YouTube: {_last_line(res.stderr)}")
    body, _, code = res.stdout.rpartition(HTTP_MARK)
    status = int(code) if code.strip().isdigit() else 0
    if status == 401:
        raise YouTubeAuthError("YouTube access ended. Connect again.")
    reasons = _reasons(body)
    if status == 403 and "accessNotConfigured" in reasons:
        raise YouTubeError("Enable the YouTube Analytics API for this app in Google Cloud, then try again")
    if status == 403 and reasons & {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT", "forbidden"}:
        raise YouTubeScopeError(scope_error)
    if status != 200:
        raise YouTubeError(_friendly(status, body))
    try:
        data = json.loads(body)
    except ValueError:
        raise YouTubeError("YouTube sent back something unexpected")
    if not isinstance(data, dict):
        raise YouTubeError("YouTube sent back something unexpected")
    return data


def video_statistics(token, ids, run=curl_run):
    """Views, likes and comments of the given videos, keyed by id. Videos YouTube no longer lists are left out."""
    query = urlencode({"part": "statistics", "id": ",".join(ids), "maxResults": STATS_BATCH})
    items = _get_json(token, f"{VIDEOS_ENDPOINT}?{query}", run, "Connect YouTube again to see views").get("items") or []
    return {item["id"]: {"views": _count(item.get("statistics") or {}, "viewCount") or 0,
                         "likes": _count(item.get("statistics") or {}, "likeCount"),
                         "comments": _count(item.get("statistics") or {}, "commentCount")}
            for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)}


def channel_identity(token, run=curl_run):
    """The signed-in channel's name and handle, {"name", "handle"}, the handle "" when the channel has none. {} when
    the account has no channel. The watermark and the title card carry these, so nothing about the channel is written
    into the code."""
    query = urlencode({"part": "snippet", "mine": "true"})
    items = _get_json(token, f"{CHANNELS_ENDPOINT}?{query}", run, "Connect YouTube again to read the channel's name").get("items") or []
    snippet = items[0].get("snippet") if items and isinstance(items[0], dict) else None
    if not isinstance(snippet, dict):
        return {}
    handle = str(snippet.get("customUrl") or "").strip()
    return {"name": str(snippet.get("title") or "").strip(), "handle": handle if handle.startswith("@") or not handle else f"@{handle}"}


def channel_videos(token, run=curl_run):
    """Every video on the signed-in channel, oldest page last as YouTube lists them: id, title and when it was published."""
    read_error = "Connect YouTube again to see the channel's videos"
    channels = _get_json(token, f"{CHANNELS_ENDPOINT}?{urlencode({'part': 'contentDetails', 'mine': 'true'})}", run, read_error).get("items") or []
    try:
        uploads = channels[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except (IndexError, KeyError, TypeError):
        return []
    videos, token_param = [], {}
    while True:
        query = urlencode({"part": "snippet", "playlistId": uploads, "maxResults": PAGE_SIZE, **token_param})
        data = _get_json(token, f"{PLAYLIST_ITEMS_ENDPOINT}?{query}", run, read_error)
        for item in data.get("items") or []:
            snippet = item.get("snippet") or {} if isinstance(item, dict) else {}
            resource = snippet.get("resourceId") or {}
            if resource.get("kind") == "youtube#video" and isinstance(resource.get("videoId"), str):
                videos.append({"video_id": resource["videoId"], "title": str(snippet.get("title") or ""), "published_at": str(snippet.get("publishedAt") or "")})
        if not data.get("nextPageToken"):
            return videos
        token_param = {"pageToken": data["nextPageToken"]}


def _report(token, params, run):
    """Rows of a YouTube Analytics report for the signed-in channel, as a list of dicts keyed by column name."""
    query = urlencode({"ids": "channel==MINE", **params})
    data = _get_json(token, f"{REPORTS_ENDPOINT}?{query}", run, "Connect YouTube again to see how much was watched")
    names = [h.get("name") for h in data.get("columnHeaders") or [] if isinstance(h, dict)]
    return [dict(zip(names, row)) for row in data.get("rows") or [] if isinstance(row, list)]


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def video_retention(token, ids, run, start, end):
    """Average seconds watched and the share of the video watched, per video id, between the dates (YYYY-MM-DD)."""
    rows = _report(token, {"startDate": start, "endDate": end, "metrics": RETENTION_METRICS, "dimensions": "video",
                           "filters": "video==" + ",".join(ids), "maxResults": STATS_BATCH}, run)
    return {str(r["video"]): {"avg_duration": _number(r.get("averageViewDuration")), "avg_percent": _number(r.get("averageViewPercentage"))}
            for r in rows if r.get("video")}


def views_by_day(token, run, start, end):
    """Views on the whole channel per day between the dates, as [{day, views}]."""
    return [{"day": str(r.get("day") or ""), "views": _number(r.get("views")) or 0} for r in _report(token, {"startDate": start, "endDate": end, "metrics": "views", "dimensions": "day"}, run)]


def retention_curve(token, video_id, run, start, end):
    """The share of viewers still watching at each hundredth of the video, first to last. Empty when YouTube has none yet."""
    rows = _report(token, {"startDate": start, "endDate": end, "metrics": "audienceWatchRatio",
                           "dimensions": "elapsedVideoTimeRatio", "filters": f"video=={video_id}"}, run)
    ordered = sorted((r for r in rows if _number(r.get("elapsedVideoTimeRatio")) is not None), key=lambda r: float(r["elapsedVideoTimeRatio"]))
    return [_number(r.get("audienceWatchRatio")) or 0.0 for r in ordered]


def _reasons(body):
    try:
        err = json.loads(body).get("error", {})
    except (ValueError, AttributeError):
        return set()
    return {e.get("reason") for e in err.get("errors", []) if isinstance(e, dict)} if isinstance(err, dict) else set()


def _split_response(text):
    """Split `curl --include` output into (status, lowercase headers, body), skipping any 1xx blocks."""
    rest = text.replace("\r\n", "\n")
    while True:
        head, sep, after = rest.partition("\n\n")
        lines = head.split("\n")
        parts = lines[0].split()
        status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        if sep and 100 <= status < 200:
            rest = after
            continue
        headers = {k.strip().lower(): v.strip() for k, _, v in (ln.partition(":") for ln in lines[1:])}
        return status, headers, after


def hashtags(text):
    """The hashtags in a description as tags, in order and without doubles, within the room YouTube gives tags."""
    tags, used = [], 0
    for tag in HASHTAG.findall(text or ""):
        if tag in tags:
            continue
        if len(tags) >= MAX_TAGS or used + len(tag) + 2 > TAGS_CHARS:
            break
        tags.append(tag)
        used += len(tag) + 2
    return tags


def validate_metadata(title, description):
    title, description = title.strip(), description.strip()
    if not title:
        raise YouTubeError("Add a title first")
    if len(title) > TITLE_LIMIT:
        raise YouTubeError(f"The title is {len(title)} characters; YouTube allows {TITLE_LIMIT}")
    if len(description) > DESCRIPTION_LIMIT:
        raise YouTubeError(f"The description is over {DESCRIPTION_LIMIT} characters")
    return title, description


def upload_video(token, path, title, description, run=curl_run, on_progress=lambda pct: None):
    path = Path(path)
    title, description = validate_metadata(title, description)
    size = path.stat().st_size
    meta = {"snippet": {"title": title, "description": description, "categoryId": CATEGORY_ENTERTAINMENT, "tags": hashtags(description)},
            "status": {"privacyStatus": UPLOAD_PRIVACY, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": False}}
    start = "".join([
        f"url = {config_value(UPLOAD_ENDPOINT)}\n", 'request = "POST"\n',
        f"header = {config_value('Authorization: Bearer ' + token)}\n",
        'header = "Content-Type: application/json; charset=UTF-8"\n',
        'header = "X-Upload-Content-Type: video/mp4"\n',
        f"header = {config_value(f'X-Upload-Content-Length: {size}')}\n",
        f"data = {config_value(json.dumps(meta))}\n"])
    res = run(["--silent", "--show-error", "--connect-timeout", "20", "--include", "--config", "-"], start)
    if res.code != 0:
        raise YouTubeError(f"Couldn't reach YouTube: {_last_line(res.stderr)}")
    status, headers, body = _split_response(res.stdout)
    if status == 401:
        raise YouTubeAuthError("YouTube access ended. Connect again.")
    if status != 200 or not headers.get("location"):
        raise YouTubeError(_friendly(status, body) if status != 200 else "YouTube didn't open an upload session")
    send = "".join([
        f"url = {config_value(headers['location'])}\n", 'request = "PUT"\n',
        f"header = {config_value('Authorization: Bearer ' + token)}\n", 'header = "Content-Type: video/mp4"\n'])
    on_progress(0)
    res = run(["--progress-bar", "--show-error", "--connect-timeout", "20", "--upload-file", str(path),
               "-w", HTTP_MARK + "%{http_code}", "--config", "-"], send,
              lambda chunk: (lambda p: on_progress(p) if p is not None else None)(last_percent(chunk)))
    if res.code != 0:
        raise YouTubeError(f"The upload was interrupted: {_last_line(res.stderr)}")
    body, _, code = res.stdout.rpartition(HTTP_MARK)
    if code.strip() == "401":
        raise YouTubeAuthError("YouTube access ended. Connect again.")
    if code.strip() not in ("200", "201"):
        raise YouTubeError(_friendly(int(code) if code.strip().isdigit() else 0, body))
    try:
        data = json.loads(body)
        video_id = data["id"]
    except (ValueError, KeyError, TypeError):
        raise YouTubeError("YouTube accepted the file but didn't say which video it is. Check YouTube Studio.")
    on_progress(100)
    privacy = (data.get("status") or {}).get("privacyStatus") if isinstance(data.get("status"), dict) else None
    return Uploaded(video_id, str(privacy or UPLOAD_PRIVACY))
