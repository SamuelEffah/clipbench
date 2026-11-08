#!/usr/bin/env python3
"""Clip bench: a local browser tool for marking clips across videos and exporting a cut list.

usage: python3 scripts/clipper.py [--port 8765] [--no-open]

Videos come from clips/ and temp/ (or a path added in the page). Anything the browser can't play
gets a small H.264 proxy in clips/.proxy/. Marks are stored against the original file, so the
render always cuts from full quality. Projects live in projects/<name>.json; Export writes
projects/<name>.cuts.txt for make_short.py.
"""
import argparse
import array
import functools
import hashlib
import html
import atexit
import json
import math
from bisect import bisect_left, bisect_right
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from concurrent.futures import Future
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import ffmpeg_env
import logbook
import logging
import reframe
import fast_speech
import mlx_speech
import liverec
import soundbank
import streamers
import tracking
import youtube as yt
from video_stats import VideoStats, best_time_text
from speech_cache import SpeechCache
import embedded_subs
import dialogue_search
import transcript_index
import clip_motion
import pauses
import prepare
import video_scan
import clip_profile
import learning
import suggest
import person_follow
import speaker_follow
import auto_layout
import cam_memory
import voice_isolation
import instrumental
from make_short import FONT_IMPACT, FONT_BOLD, FONT_REGULAR, FONT_EMOJI, CAPMODES, HEX_COLOUR, LOOKS, MAX_AUDIO_ITEMS, MAX_WORDS, CAPTION_SIZES, SPLIT_RANGE, probe_duration, DEFAULT_FORMAT, FORMATS, LAYOUTS, RAMPS, SUB_FONT_SIZE, TEMPLATES, LANES, LANE_COUNT, TRANSITIONS, joined_length, out_length
from publisher import CALLBACK_PATH, Publisher
from shorts import current_upload, list_shorts, thumbnail, with_stats
from store import Store
from thumbnails import ThumbnailStore

ROOT = Path(__file__).resolve().parent.parent
from color_grade import GRADE_DEFAULTS, GRADE_RANGES

UI_DIR = Path(__file__).resolve().parent / "clipper_ui"
# Everything the bench downloads, makes or remembers lives under one folder, so the code sits beside it untouched.
WORKSPACE = Path(os.environ.get("CLIPBENCH_WORKSPACE") or ROOT / "workspace")
PROXY_DIR = WORKSPACE / "clips" / ".proxy"
PROJECT_DIR = WORKSPACE / "projects"
AVATAR_FILE = WORKSPACE / "channel" / "avatar.png"
LOG_FILE = WORKSPACE / "logs" / "clipbench.log"
log = logging.getLogger("clipbench")
http_log = logging.getLogger("clipbench.http")
DATA_DIR = Path(os.environ.get("CLIPBENCH_DATA") or WORKSPACE / "data")
DB_FILE = DATA_DIR / "clipbench.db"
CLIP_THUMB_DIR = DATA_DIR / "clip-thumbs"
CLIENT_FILE = DATA_DIR / "youtube_client.json"
STREAMER_FILE = DATA_DIR / "streamers.json"
recorder = liverec.Recorder(DATA_DIR / "live")
cams = cam_memory.CamMemory(DATA_DIR / "cams.json")
FAVORITES_LIMIT = 300
BROLL_DIR = WORKSPACE / "broll"
LIBRARY_DIRS = [WORKSPACE / "clips", WORKSPACE / "temp", BROLL_DIR]
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
DIRECT_EXTS = {".mp4", ".m4v", ".mov"}
AUDIO_DIR = WORKSPACE / "audio"
AUDIO_DIRS = [AUDIO_DIR, WORKSPACE / "music"]
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".aiff", ".aif"}
AUDIO_TYPES = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg",
               ".flac": "audio/flac", ".aiff": "audio/aiff", ".aif": "audio/aiff"}
SFX_MAX_SECONDS = 10


def audio_suffix(head, fallback=".mp3"):
    """The file extension an audio file's first bytes call for, since a download or an old import can carry the wrong one."""
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return ".wav"
    if head[:4] == b"OggS":
        return ".ogg"
    if head[:4] == b"fLaC":
        return ".flac"
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return ".aiff"
    if head[4:8] == b"ftyp":
        return ".m4a"
    if head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return ".mp3"
    return fallback


def audio_type(path):
    """The Content-Type for a sound, from what is in the file, so a WAV saved as .mp3 still plays in a strict browser."""
    with open(path, "rb") as f:
        head = f.read(12)
    suffix = audio_suffix(head, path.suffix.lower())
    return AUDIO_TYPES.get(suffix, "audio/mpeg")
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,60}$")

lock = threading.Lock()
store = None
publisher = None
video_stats = None
registry = {}
proxies = {}


def media_key(path):
    """What a video is known by: its place inside the workspace, so the workspace can move or the bench be cloned
    anywhere without its proxies, transcripts and suggestions becoming strangers; a file elsewhere keeps its full path."""
    p = Path(path)
    try:
        return p.relative_to(WORKSPACE).as_posix()
    except ValueError:
        return str(path)


def video_id(path):
    return hashlib.sha1(media_key(path).encode()).hexdigest()[:12]


transcript_index.key_of = media_key


_probes = {}
_pending_probes = {}


METADATA_CACHE_LIMIT = 1024


def _remember_metadata(cache, key, value):
    """Called under lock: retain one version per path and recent entries only."""
    for previous in list(cache):
        if previous[0] == key[0]:
            cache.pop(previous)
    cache[key] = value
    while len(cache) > METADATA_CACHE_LIMIT:
        cache.pop(next(iter(cache)))


def probe(path):
    """Duration plus first video/audio codec, or None if ffprobe can't read the file. Remembered until the file changes."""
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    with lock:
        if key in _probes:
            value = _probes.pop(key)
            _probes[key] = value
            return value
        pending = _pending_probes.get(key)
        owner = pending is None
        if owner:
            pending = _pending_probes[key] = Future()
    if not owner:
        return pending.result()
    # Library, subtitle and thumbnail requests can arrive together. Share their
    # metadata work without holding the global lock while ffprobe runs.
    try:
        meta = _probe(path)
        with lock:
            _remember_metadata(_probes, key, meta)
        pending.set_result(meta)
        return meta
    except BaseException as err:
        pending.set_exception(err)
        raise
    finally:
        with lock:
            _pending_probes.pop(key, None)


def _probe(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,pix_fmt",
             "-of", "json", str(path)], capture_output=True, text=True)
        info = json.loads(out.stdout or "{}") if out.returncode == 0 else None
    except (OSError, ValueError):
        return None
    if info is None:
        return None
    codecs = {}
    size = (0, 0)
    pixel_format = None
    for st in info.get("streams", []):
        if st.get("codec_type") not in codecs:
            codecs[st.get("codec_type")] = st.get("codec_name")
            if st.get("codec_type") == "video":
                size = (st.get("width") or 0, st.get("height") or 0)
                pixel_format = st.get("pix_fmt")
    return {"duration": float(info.get("format", {}).get("duration") or 0),
            "video": codecs.get("video"), "audio": codecs.get("audio"), "width": size[0], "height": size[1],
            "pixel_format": pixel_format}


def plays_directly(path, meta):
    return (path.suffix.lower() in DIRECT_EXTS and meta["video"] == "h264"
            and meta["audio"] in (None, "aac", "mp3"))


def proxy_path(vid):
    return PROXY_DIR / f"{vid}.mp4"


def _file_stamp(src):
    stat = Path(src).stat()
    return (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)


_pending_thumbs = {}


def video_thumb(vid):
    """Share cover-frame generation and publish a complete JPEG beside the proxies."""
    src = registry.get(vid)
    if not src or not src.is_file():
        return None
    try:
        stamp = _file_stamp(src)
    except OSError:
        return None
    thumb = PROXY_DIR / f"{vid}.jpg"
    key = (str(thumb), str(src), stamp)
    with lock:
        pending = _pending_thumbs.get(key)
        owner = pending is None
        if owner:
            pending = _pending_thumbs[key] = Future()
    if not owner:
        return pending.result()
    tmp = None
    try:
        result = None
        if thumb.is_file() and thumb.stat().st_mtime_ns >= stamp[1]:
            result = thumb
        else:
            meta = probe(src)
            length = meta["duration"] if meta else 0
            at = min(max(1.0, length * 0.1), length / 2) if length else 0
            PROXY_DIR.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=PROXY_DIR, suffix=".jpg", delete=False) as out:
                tmp = Path(out.name)
            out = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{at:.2f}", "-i", str(src), "-frames:v", "1",
                                  "-vf", "scale=320:-2", "-q:v", "5", str(tmp)], capture_output=True)
            try:
                unchanged = _file_stamp(src) == stamp
            except OSError:
                unchanged = False
            if out.returncode == 0 and tmp.stat().st_size and unchanged:
                tmp.replace(thumb)
                result = thumb
        pending.set_result(result)
        return result
    except BaseException as exc:
        pending.set_exception(exc)
        raise
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
        with lock:
            _pending_thumbs.pop(key, None)


WAVE_RATE = 8000
WAVE_PER_SEC = 20


def wave_path(vid):
    return PROXY_DIR / f"{vid}.wave.json"


def _read_wave_peaks(stream, step):
    """Reduce PCM in bounded chunks, keeping incomplete buckets for the next read."""
    bucket_bytes = step * 2
    pending, raw = b"", []
    while chunk := stream.read(bucket_bytes * 128):
        pending += chunk
        end = len(pending) // bucket_bytes * bucket_bytes
        samples = array.array("h")
        samples.frombytes(pending[:end])
        raw.extend(max(map(abs, samples[i:i + step])) for i in range(0, len(samples), step))
        pending = pending[end:]
    if len(pending) >= 2:
        samples = array.array("h")
        samples.frombytes(pending[:len(pending) // 2 * 2])
        raw.append(max(map(abs, samples)))
    return raw


def compute_wave(src, per_sec=WAVE_PER_SEC):
    """Loudness peaks of the first audio track, per_sec buckets a second, scaled 0 to 255.

    The loudest 1% is clipped so one explosion doesn't flatten the rest of the episode.
    """
    with subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(src), "-map", "0:a:0", "-ac", "1", "-ar", str(WAVE_RATE),
         "-f", "s16le", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        raw = _read_wave_peaks(proc.stdout, WAVE_RATE // per_sec)
        failed = proc.wait() != 0
    if failed or not raw:
        return {"per_sec": per_sec, "peaks": []}
    ceiling = sorted(raw)[int(len(raw) * 0.99)] or 1
    return {"per_sec": per_sec, "peaks": [min(255, round(v / ceiling * 255)) for v in raw]}


AUDIO_WAVE_PER_SEC = 50
_pending_waves = {}
_wave_memory = OrderedDict()
WAVE_MEMORY_ENTRIES = 8
WAVE_MEMORY_PEAKS = 500_000


def _wave_cache_stamp(path):
    try:
        return _file_stamp(path)
    except OSError:
        return None


def _remember_wave(key, wave):
    if not isinstance(wave, dict) or not isinstance(wave.get("peaks"), list):
        return
    if len(wave["peaks"]) > WAVE_MEMORY_PEAKS:
        return
    with lock:
        _wave_memory[key] = wave
        _wave_memory.move_to_end(key)
        while (len(_wave_memory) > WAVE_MEMORY_ENTRIES
               or sum(len(w["peaks"]) for w in _wave_memory.values()) > WAVE_MEMORY_PEAKS):
            _wave_memory.popitem(last=False)



def _cached_wave(src, cache, per_sec):
    """Share an in-flight decode and publish only complete waveform JSON."""
    stamp = _file_stamp(src)
    key = (str(cache), str(src), stamp, per_sec)
    memory_key = (*key, _wave_cache_stamp(cache))
    with lock:
        if memory_key in _wave_memory:
            _wave_memory.move_to_end(memory_key)
            return _wave_memory[memory_key]
        pending = _pending_waves.get(key)
        owner = pending is None
        if owner:
            pending = _pending_waves[key] = Future()
    if not owner:
        return pending.result()
    tmp = None
    try:
        if cache.is_file() and cache.stat().st_mtime_ns >= stamp[1]:
            wave = json.loads(cache.read_text())
        else:
            wave = compute_wave(src, per_sec)
            cache.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", dir=cache.parent, suffix=".tmp", delete=False) as out:
                tmp = Path(out.name)
                json.dump(wave, out)
            # A source replaced during decoding needs a new waveform next time.
            if _file_stamp(src) == stamp:
                tmp.replace(cache)
        cache_stamp = _wave_cache_stamp(cache)
        if cache_stamp is not None and _file_stamp(src) == stamp:
            _remember_wave((*key, cache_stamp), wave)
        pending.set_result(wave)
        return wave
    except BaseException as exc:
        pending.set_exception(exc)
        raise
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
        with lock:
            _pending_waves.pop(key, None)


def load_audio_wave(vid):
    """Peaks for a song or sound effect, fine enough to draw a short effect, cached until the file changes."""
    src = audio_registry.get(vid)
    if not src or not src.is_file():
        scan_audio()
        src = audio_registry.get(vid)
    if not src or not src.is_file():
        return None
    return _cached_wave(src, PROXY_DIR / f"{vid}.audiowave.json", AUDIO_WAVE_PER_SEC)


def load_wave(vid):
    src = registry.get(vid)
    if not src:
        return None
    return _cached_wave(src, wave_path(vid), WAVE_PER_SEC)


SCENE_THRESHOLD = 0.3
SCENE_MIN_GAP = 0.5
SCENE_TIME_RE = re.compile(r"pts_time:(\d+(?:\.\d+)?)")
scene_jobs = {}
scene_finished = threading.Condition(lock)


def scene_path(vid):
    return PROXY_DIR / f"{vid}.scenes.json"


def detect_scenes(src):
    """Times (seconds) where the picture cuts hard, from ffmpeg's scene score on a small copy of the video."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "info", "-nostats", "-i", str(src), "-an", "-sn", "-vf",
         f"scale=320:-2,select='gt(scene,{SCENE_THRESHOLD})',showinfo", "-f", "null", "-"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    times = []
    for m in SCENE_TIME_RE.finditer(proc.stderr):
        t = float(m.group(1))
        if not times or t - times[-1] >= SCENE_MIN_GAP:
            times.append(round(t, 2))
    return times


def run_scenes(vid):
    try:
        src = registry.get(vid)
        source = proxy_path(vid) if proxy_path(vid).is_file() else src
        times = None
        if source:
            # One decode gives the cuts and the picture motion, so the motion is saved too and suggestions need no second scan.
            times, motion = video_scan.scan(source, SCENE_THRESHOLD, SCENE_MIN_GAP)
            if times is not None:
                PROXY_DIR.mkdir(parents=True, exist_ok=True)
                scene_path(vid).write_text(json.dumps(times))
                if motion and motion["values"]:
                    motion_path(vid).write_text(json.dumps(motion))
    except Exception as err:
        log.exception("scene scan {vid}")
        times = None
    with scene_finished:
        if times is None:
            scene_jobs[vid] = {"state": "error", "message": "Couldn't scan this video for scene cuts"}
        else:
            scene_jobs[vid] = {"state": "ready", "scenes": times}
        scene_finished.notify_all()


_scene_data = OrderedDict()
SCENE_DATA_LIMIT = 32


def read_scenes(path):
    """Reuse unchanged scene JSON, keeping only a bounded set of file versions."""
    path = Path(path)
    stamp = _wave_cache_stamp(path)
    with lock:
        cached = _scene_data.get(path)
        if stamp is not None and cached and cached[0] == stamp:
            _scene_data.move_to_end(path)
            return list(cached[1])
        _scene_data.pop(path, None)
        scenes = json.loads(path.read_text())
        if stamp is not None and _wave_cache_stamp(path) == stamp:
            _scene_data[path] = (stamp, scenes)
            while len(_scene_data) > SCENE_DATA_LIMIT:
                _scene_data.popitem(last=False)
        return list(scenes)


def get_scenes(vid):
    src = registry.get(vid)
    if not src:
        return {"state": "error", "message": "unknown video"}
    cache = scene_path(vid)
    if cache.is_file() and cache.stat().st_mtime >= Path(src).stat().st_mtime:
        return {"state": "ready", "scenes": read_scenes(cache)}
    with lock:
        job = scene_jobs.get(vid)
        if job and job["state"] == "working":
            return job
        if job and job["state"] == "error":
            scene_jobs.pop(vid)
            return job
        scene_jobs[vid] = {"state": "working"}
    threading.Thread(target=run_scenes, args=(vid,), daemon=True).start()
    return {"state": "working"}


person_follow.CACHE_DIR = PROXY_DIR / "follow"
follow_jobs = {}
follow_turn = threading.Lock()
FOLLOW_JOBS_KEPT = 20


def followed_people(src, start, end, box, at, progress=None):
    """Follow a person inside the box with the person detector, or None when it is not installed or no one is in the box."""
    if not person_follow.available():
        return None
    try:
        return person_follow.follow_person(src, start, end, box, at=at, progress=progress)
    except (ImportError, person_follow.NoPerson):
        return None


def run_follow(job, src, start, end, box, at):
    """Follow what is inside the box: a person with the detector, anything else with the older tracker. One at a time, since each uses the whole machine."""
    try:
        with follow_turn:
            job.update(state="working")
            found = followed_people(src, start, end, box, at, progress=lambda done, total: job.update(pct=round(done / total * 100)))
            found = found or reframe.follow_subject(src, start, end, box, at=at)
            width, height = reframe.probe_size(src)
        job.update(state="ready", pct=100, width=width, height=height,
                   track=tracking.simplify(tracking.smooth(found["samples"], window=3, max_speed=tracking.FOLLOW_SPEED)))
    except (ImportError, AttributeError):
        job.update(state="error", message="Following needs OpenCV 4: pip install 'opencv-python-headless<5'")
    except (ValueError, OSError, subprocess.SubprocessError) as err:
        job.update(state="error", message=str(err)[:300])


_reframe_results = OrderedDict()
_pending_reframes = {}
REFRAME_CACHE_LIMIT = 32


def reframe_analysis(src, start, end):
    """Reuse completed analyses and share matching work without caching failed decodes."""
    stamp, model = _file_stamp(src), _wave_cache_stamp(reframe.ANIME_CASCADE)
    key = (src, stamp, start, end, model)
    with lock:
        cached = _reframe_results.get(key)
        if cached is not None:
            _reframe_results.move_to_end(key)
        pending = _pending_reframes.get(key)
        owner = cached is None and pending is None
        if owner:
            pending = _pending_reframes[key] = Future()
    if cached is not None:
        return deepcopy(cached)
    if not owner:
        return deepcopy(pending.result())
    try:
        found = reframe.find_faces(src, start, end)
        width, height = reframe.probe_size(src)
        result = {**found, "track": tracking.simplify(tracking.smooth(found["samples"])), "width": width, "height": height}
        if (found["looked"] and _file_stamp(src) == stamp
                and _wave_cache_stamp(reframe.ANIME_CASCADE) == model):
            with lock:
                _reframe_results[key] = result
                while len(_reframe_results) > REFRAME_CACHE_LIMIT:
                    _reframe_results.popitem(last=False)
        pending.set_result(result)
        return deepcopy(result)
    except BaseException as err:
        pending.set_exception(err)
        raise
    finally:
        with lock:
            _pending_reframes.pop(key, None)


def speaker_analysis(src, start, end):
    """Where the crop should sit to stay on whoever is talking, with the words when they are already known, else the sound level."""
    if not speaker_follow.available():
        raise ValueError("Follow the speaker needs scripts/models/face_detection_yunet_2023mar.onnx")
    result = speaker_follow.follow_speaker(src, start, end, words=speech_cache().find(src, start, end))
    width, height = reframe.probe_size(src)
    track = tracking.simplify(result["track"])
    return {**result, "samples": track, "track": track, "width": width, "height": height}


def layout_analysis(src, start, end):
    """Which layout suits this clip, from the faces in it, with the picture's size for working out the crops."""
    if not auto_layout.available():
        raise ValueError("Auto layout needs scripts/models/face_detection_yunet_2023mar.onnx")
    width, height = reframe.probe_size(src)
    found = auto_layout.analyze(src, start, end, remembered=cams.recall(src, width, height))
    if found["layout"] == "webcam" and not found.get("guessed") and not found.get("remembered") and found.get("share", 0) >= auto_layout.CAM_THROUGHOUT:
        # A cam found from its own border through the whole clip is the stream's cam: the next clip of the stream starts from it.
        try:
            cams.remember(src, width, height, found["webcam"])
        except OSError as err:
            log.exception("cam memory for {src}")
    return {**found, "width": width, "height": height}


def start_follow(src, start, end, box, at):
    job_id = os.urandom(6).hex()
    job = {"state": "queued", "pct": 0}
    with lock:
        for old in [k for k, j in follow_jobs.items() if j["state"] in ("ready", "error")][:-FOLLOW_JOBS_KEPT]:
            follow_jobs.pop(old, None)
        follow_jobs[job_id] = job
    threading.Thread(target=run_follow, args=(job, src, start, end, box, at), daemon=True).start()
    return {"id": job_id, **job}


suggest_jobs = {}


def suggest_path(vid):
    return PROXY_DIR / f"{vid}.suggest.json"


def motion_path(vid):
    return PROXY_DIR / f"{vid}.motion.json"


def load_motion(vid, src):
    """How much the picture moves in a video, measured once and kept until the file changes. None when it cannot be measured."""
    cache = motion_path(vid)
    try:
        if cache.is_file() and cache.stat().st_mtime >= Path(src).stat().st_mtime:
            saved = json.loads(cache.read_text())
            if saved.get("values"):
                return saved
        source = proxy_path(vid) if proxy_path(vid).is_file() else src
        found = clip_motion.compute(source)
        if not found["values"]:
            return None
        PROXY_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(found))
        return found
    except (OSError, ValueError, AttributeError) as err:
        log.exception("motion {vid}")
        return None


def run_suggest(vid):
    """Find the clips worth cutting in one video, from its subtitles, scene cuts and loudness, and from a local model when one is running."""
    src = registry.get(vid)
    job = suggest_jobs[vid]
    try:
        cues = dialogue_cues(src) if src else None
        if cues is None:
            job.update(state="error", message="Listen to this video first, or use a video with English subtitles")
            return
        wave = load_wave(vid) or {}
        scene_state = get_scenes(vid)
        if scene_state.get("state") == "working":
            # get_scenes already started a whole-video decode. Share its result
            # instead of launching a competing scan in the suggestion worker.
            with scene_finished:
                while scene_jobs.get(vid, {}).get("state") == "working":
                    scene_finished.wait()
                scene_state = scene_jobs.get(vid, {})
        scenes = scene_state.get("scenes")
        if scenes is None:
            source = proxy_path(vid) if proxy_path(vid).is_file() else src
            scenes = detect_scenes(source) or []
        meta = probe(src)
        model = suggest.pick_model(suggest.ollama_models())
        job.update(model=model or "")
        peaks, per_sec = wave.get("peaks", []), wave.get("per_sec", WAVE_PER_SEC)
        kind = clip_profile.profile(cues, meta["duration"], scenes, peaks, per_sec)
        found = suggest.suggest(cues, meta["duration"], scenes, peaks, per_sec, model,
                                progress=lambda done, total: job.update(pct=round(done / total * 100)), profile=kind,
                                motion=load_motion(vid, src), partial=lambda clips: job.update(clips=clips, profile=kind))
        result = {"state": "ready", "clips": found, "model": model or "", "profile": kind, "version": suggest.VERSION}
        PROXY_DIR.mkdir(parents=True, exist_ok=True)
        suggest_path(vid).write_text(json.dumps(result))
        suggest_jobs[vid] = result
    except (OSError, ValueError, TypeError, KeyError) as err:
        log.exception("suggest {vid}")
        suggest_jobs[vid] = {"state": "error", "message": "Couldn't look for clips in this video"}


def dialogue_cues(src):
    """The lines said in a video: its English subtitles, else what was heard when it was listened to. None when it has neither."""
    cues = embedded_subs.all_cues(str(src))
    return cues if cues is not None else transcript_index.load(DATA_DIR, src)


index_jobs = {}


def listen_whole(src):
    """Whisper's result for a whole video, in English. Raises when nothing can listen or the video has no sound."""
    exe = speech_engine()
    if not exe:
        raise RuntimeError(WHISPER_HINT)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "all.wav"
        cut = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", str(wav)],
                             capture_output=True, text=True)
        if cut.returncode != 0 or not wav.is_file():
            raise RuntimeError("This video has no audio to listen to")
        result, problem = whisper_json(exe, wav, tmp, "translate", False)
    if result is None:
        raise RuntimeError(problem)
    return result


def run_index(vid):
    src = registry.get(vid)
    try:
        transcript_index.build(DATA_DIR, src, listen_whole)
        state = {"state": "ready"}
    except Exception as err:
        log.exception("listen {vid}")
        state = {"state": "error", "message": f"Couldn't listen to this video: {err}"[:300]}
    with lock:
        index_jobs[vid] = state


def start_index(vid):
    """Listen to a video in the background so its dialogue can be searched. One job per video at a time."""
    with lock:
        src = registry.get(vid)
        if not src or not Path(src).is_file():
            return {"state": "error", "message": "unknown video"}
        if index_jobs.get(vid, {}).get("state") == "working":
            return index_jobs[vid]
        index_jobs[vid] = {"state": "working"}
    threading.Thread(target=run_index, args=(vid,), daemon=True).start()
    return {"state": "working"}


def search_dialogue(query, project=None):
    """What is said, matched across the videos the project can see that have English subtitles or have been listened to. Scene cuts come from the scans already saved; a video not scanned yet is framed without them.
    `unheard` lists the videos with neither, which the page offers to listen to."""
    visible = {item["id"] for item in scan_library(project) if not item["broll"]}
    with lock:
        sources = [(vid, src) for vid, src in registry.items() if vid in visible]
        working = {vid for vid, job in index_jobs.items() if job.get("state") == "working"}
    videos, unheard = [], []
    searching = len(query.strip()) >= dialogue_search.MIN_QUERY
    for vid, src in sources:
        try:
            cues = dialogue_cues(src) if Path(src).is_file() else None
            if cues is None:
                if Path(src).is_file():
                    unheard.append({"id": vid, "name": Path(src).name, "working": vid in working})
                continue
            scenes = []
            if searching and cues:
                cache = scene_path(vid)
                scenes = read_scenes(cache) if cache.is_file() else []
            meta = probe(src) if cues else None
        except (OSError, ValueError):
            continue
        if cues and meta:
            videos.append((vid, Path(src).name, str(src), meta["duration"], cues, scenes))
    found = dialogue_search.search(videos, query) if searching else []
    return {"results": found, "videos": len(videos), "unheard": unheard}


REVIEW_DECISIONS = ("keep", "skip")
MOMENT_KEYS = ("text", "why", "parts", "score", "profile")
MOMENT_TEXT_MAX = 2000


def review_suggestion(vid, body):
    """Save what was decided about a suggested moment: body {in, out, decision: keep|skip|null, moment: {...}}."""
    if vid not in registry:
        raise ValueError("unknown video")
    if not isinstance(body, dict):
        raise ValueError("bad request")
    try:
        start, end = float(body["in"]), float(body["out"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("bad range")
    if not (0 <= start < end) or not math.isfinite(end):
        raise ValueError("bad range")
    decision = body.get("decision")
    if decision is not None and decision not in REVIEW_DECISIONS:
        raise ValueError("decision must be keep, skip or null")
    moment = body.get("moment") or {}
    if not isinstance(moment, dict):
        raise ValueError("bad moment")
    kept = {k: moment[k] for k in MOMENT_KEYS if k in moment}
    if len(json.dumps(kept)) > MOMENT_TEXT_MAX:
        raise ValueError("moment too long")
    store.review_suggestion(vid, start, end, decision, kept)
    forget_lessons()
    return {"ok": True}


LESSONS_FRESH_FOR = 60  # seconds the lessons from past decisions and published Shorts are reused before being worked out again
_lessons = None  # (worked out at, lessons)


def forget_lessons():
    """Drop the cached lessons so the next ranking works them out again, as after a new decision."""
    global _lessons
    _lessons = None


def saved_suggestions(src):
    """The suggestions last saved for a video, whatever version made them, each carrying the kind of video. [] without any."""
    try:
        saved = json.loads(suggest_path(video_id(src)).read_text())
        kind = (saved.get("profile") or {}).get("kind")
        return [{**c, "profile": kind} if kind else c for c in saved.get("clips") or [] if isinstance(c, dict)]
    except (OSError, ValueError, AttributeError, TypeError):
        return []


def build_lessons():
    """What past decisions and published Shorts say about each kind of moment. Never raises: a bench that cannot be read teaches nothing."""
    try:
        shorts = list_shorts(SHORT_DIR, store.list_projects(), publisher.state, short_duration)
        examples = learning.review_examples(store.suggestion_reviews())
        examples += learning.published_examples(learning.published(shorts, store.channel_videos()), store.video_stats(), rendered_project, saved_suggestions)
        return learning.lessons(examples)
    except Exception as err:
        log.exception("lessons could not be worked out")
        return {}


def current_lessons():
    """The lessons, worked out again at most once a minute."""
    global _lessons
    now = time.time()
    if _lessons is None or now - _lessons[0] >= LESSONS_FRESH_FOR:
        _lessons = (now, build_lessons())
    return _lessons[1]


def ranked(result):
    """A result with its clips re-ranked by what earlier suggestions taught, finished or still filling in. The saved file
    and the running job keep the scores as measured."""
    if not result.get("clips"):
        return result
    kind = (result.get("profile") or {}).get("kind") if isinstance(result.get("profile"), dict) else None
    return {**result, "clips": learning.adjust(result["clips"], current_lessons(), profile=kind)}


def get_suggest(vid):
    """The saved suggestions for a video, or the running job."""
    with lock:
        job = suggest_jobs.get(vid)
    if job and (job.get("state") != "ready" or job.get("version") == suggest.VERSION):
        return ranked(job)
    src = registry.get(vid)
    cache = suggest_path(vid)
    if src and cache.is_file() and cache.stat().st_mtime >= Path(src).stat().st_mtime:
        try:
            saved = json.loads(cache.read_text())
            if saved.get("version") == suggest.VERSION:
                return ranked(saved)
        except (OSError, ValueError, AttributeError):
            pass
    return {"state": "none"}


def start_suggest(vid):
    if vid not in registry:
        return {"state": "error", "message": "unknown video"}
    with lock:
        job = suggest_jobs.get(vid)
        if job and job["state"] == "working":
            return job
        suggest_jobs[vid] = {"state": "working", "pct": 0, "model": ""}
    threading.Thread(target=run_suggest, args=(vid,), daemon=True).start()
    return {"state": "working", "pct": 0, "model": ""}


PREPARE_POLL = 1.0
auto_prepare = os.environ.get("CLIPBENCH_PREPARE", "1") != "0"


def wait_while(working):
    """Block until working() is false, checking once a second."""
    while working():
        time.sleep(PREPARE_POLL)


class LoggedServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        http_log.exception("request from %s:%s crashed", *client_address[:2])


def _logged_step(vid, step):
    def logged(label):
        logging.getLogger("clipbench.prepare").info("%s: %s", vid, label)
        step(label)
    return logged


def prepare_video(vid, step):
    """Scan and listen to a video, then rank its clips, so suggestions are waiting when it is opened.
    Scanning decodes video and listening runs on the GPU, so they overlap; ranking needs both."""
    src = registry.get(vid)
    if not src or not Path(src).is_file():
        raise ValueError("unknown video")
    step = _logged_step(vid, step)
    step("Scanning")
    get_scenes(vid)
    listening = None
    if dialogue_cues(src) is None and speech_engine():
        step("Listening")
        listening = start_index(vid)
    wait_while(lambda: scene_jobs.get(vid, {}).get("state") == "working")
    if listening:
        wait_while(lambda: index_jobs.get(vid, {}).get("state") == "working")
    if dialogue_cues(src) is None:
        return
    step("Finding clips")
    suggest.warm(suggest.pick_model(suggest.ollama_models()))
    start_suggest(vid)
    wait_while(lambda: suggest_jobs.get(vid, {}).get("state") == "working")


prepare_queue = prepare.Queue(prepare_video)


def prepare_after_download(path):
    """Start getting a finished download ready. Never raises: this is a courtesy, not part of the download."""
    if not auto_prepare:
        return
    try:
        p = Path(path)
        vid = video_id(p)
        with lock:
            registry[vid] = p
        prepare_queue.add(vid)
    except Exception as err:
        log.exception("prepare after download")


RENDER_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
SHORT_DIR = WORKSPACE / "shorts"
renders = {}


durations = {}


def short_duration(path):
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    with lock:
        if key in durations:
            value = durations.pop(key)
            durations[key] = value
            return value
    meta = probe(path)
    value = meta["duration"] if meta else None
    with lock:
        _remember_metadata(durations, key, value)
    return value


def short_folder(name):
    """The shorts/NNN_name folder for a project, numbered after the last one when it's new."""
    SHORT_DIR.mkdir(exist_ok=True)
    project_pattern = re.compile(rf"\d{{3}}_{re.escape(name)}")
    latest = 0
    for d in sorted(SHORT_DIR.iterdir()):
        if not re.match(r"\d{3}_", d.name) or not d.is_dir():
            continue
        if project_pattern.fullmatch(d.name):
            return d
        latest = max(latest, int(d.name[:3]))
    return SHORT_DIR / f"{latest + 1:03d}_{name}"


VOICE_DIR = DATA_DIR / "voice"
voice_jobs = {}


instrumental_jobs = {}
instrumental_lock = threading.Lock()


def start_instrumental(src):
    done = instrumental.target_for(src).is_file()
    job = {"id": hashlib.sha1(f"{src}{time.time()}".encode()).hexdigest()[:12], "state": "done" if done else "working",
           "message": "Taking the singing out"}
    instrumental_jobs[job["id"]] = job
    if not done:
        threading.Thread(target=run_instrumental, args=(job["id"], src), daemon=True).start()
    return job


def run_instrumental(job_id, src):
    try:
        with instrumental_lock:
            instrumental.make_instrumental(src)
        instrumental_jobs[job_id] = {"id": job_id, "state": "done"}
    except ValueError as err:
        instrumental_jobs[job_id] = {"id": job_id, "state": "error", "message": str(err)[:300]}
    except Exception as err:
        log.exception("instrumental {job_id}")
        instrumental_jobs[job_id] = {"id": job_id, "state": "error", "message": f"Couldn't take the singing out: {err}"[:300]}


def rounded_range(start, end):
    """The range as the cut list writes it, which is what a render cuts."""
    return float(fmt_time(start)), float(fmt_time(end))


def voice_file_url(target):
    """Where the page plays a saved voice from."""
    return f"/voice/{target.name}"


def start_voice(src, start, end):
    start, end = rounded_range(start, end)
    target = voice_isolation.cached_path(VOICE_DIR, src, start, end)
    job_id = hashlib.sha1(f"{target}{time.time()}".encode()).hexdigest()[:12]
    if target.is_file():
        job = {"id": job_id, "state": "done", "file": voice_file_url(target)}
    else:
        job = {"id": job_id, "state": "working", "message": "Taking the music out"}
    voice_jobs[job["id"]] = job
    if job["state"] == "working":
        threading.Thread(target=run_voice, args=(job["id"], src, start, end), daemon=True).start()
    return job


def run_voice(job_id, src, start, end):
    try:
        target = voice_isolation.isolate(VOICE_DIR, src, start, end)
        voice_jobs[job_id] = {"id": job_id, "state": "done", "file": voice_file_url(target)}
    except ValueError as err:
        voice_jobs[job_id] = {"id": job_id, "state": "error", "message": str(err)[:300]}
    except Exception as err:
        log.exception("voice {job_id}")
        voice_jobs[job_id] = {"id": job_id, "state": "error", "message": f"Couldn't isolate the voice: {err}"[:300]}


WHISPER_MODEL = "small"
WHISPER_CACHE = Path.home() / ".cache" / "whisper"
WHISPER_HINT = "Speech to text isn't installed. In Terminal run: ./setup.sh --ai"
SLOW_ENGINE_HINT = "on the CPU, which takes minutes; ./setup.sh --ai installs the fast engine"
MAX_CAPTION = 120
MAX_TRANSCRIBE = 60.0
transcripts = {}
_pending_transcribes = {}


def trim_caption(text):
    """The first whole sentences of a transcript that fit the caption limit."""
    text = " ".join(text.split())
    if len(text) <= MAX_CAPTION:
        return text
    kept = ""
    for sentence in re.findall(r"[^.!?]+[.!?]*\s*", text):
        if len(kept) + len(sentence.strip()) > MAX_CAPTION:
            break
        kept = f"{kept} {sentence.strip()}".strip()
    return kept or text[:MAX_CAPTION].rsplit(" ", 1)[0]


def spoken_words(result):
    """[text, start, end] for each word Whisper timed, in seconds from the start of what it heard."""
    words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            text = str(w.get("word", "")).strip()
            a, b = float(w.get("start", 0)), float(w.get("end", 0))
            if text and b > a:
                words.append([text[:40], round(a, 2), round(b, 2)])
    return words[:MAX_WORDS]


def speech_engine():
    """What listens: the Mac GPU engine when it is installed, else the faster in-process engine, else the whisper command line, else None."""
    if mlx_speech.available():
        return "mlx"
    return "fast" if fast_speech.available() else shutil.which("whisper")


def listening_message(exe, first_run):
    """Status for a listening job: plain for the in-process engines, a warning when the whisper command line is all there is."""
    if exe in ("mlx", "fast"):
        return "Listening"
    if first_run:
        return f"Downloading the speech model, first time only, then listening {SLOW_ENGINE_HINT}"
    return f"Listening {SLOW_ENGINE_HINT}"


def start_transcribe(src, start, end, timed=False, task="translate"):
    """Share an in-flight listening request; finished and failed jobs remain retryable."""
    exe = speech_engine()
    if not exe and not (task == "translate" and embedded_subs.has_subtitles(src)):
        return {"state": "error", "message": WHISPER_HINT}
    first_run = exe not in (None, "fast", "mlx") and not (WHISPER_CACHE / f"{WHISPER_MODEL}.pt").is_file()
    try:
        version = _file_stamp(src)
    except OSError:
        version = None
    key = (str(src), version, start, end, bool(timed), task, exe)
    with lock:
        pending_id = _pending_transcribes.get(key)
        pending = transcripts.get(pending_id)
        if pending and pending.get("state") == "working":
            return pending
        job = {"id": hashlib.sha1(f"{src}{start}{end}{time.time()}".encode()).hexdigest()[:12], "state": "working",
               "message": listening_message(exe, first_run)}
        transcripts[job["id"]] = job
        _pending_transcribes[key] = job["id"]
    try:
        threading.Thread(target=_run_pending_transcribe, args=(key, job["id"], exe, src, start, end, timed, task), daemon=True).start()
    except BaseException as err:
        with lock:
            if _pending_transcribes.get(key) == job["id"]:
                _pending_transcribes.pop(key, None)
            transcripts[job["id"]] = {"id": job["id"], "state": "error", "message": f"Couldn't start listening: {err}"[:300]}
        raise
    return job


def _run_pending_transcribe(key, job_id, exe, src, start, end, timed, task):
    try:
        run_transcribe(job_id, exe, src, start, end, timed, task)
    finally:
        with lock:
            if _pending_transcribes.get(key) == job_id:
                _pending_transcribes.pop(key, None)


def whisper_json(exe, wav, tmp, task, timed):
    """Listen to a wav and return the parsed json, or an error message. Uses the in-process engine when there is one,
    and the whisper command line if that is all there is or the engine could not start."""
    if exe == "mlx":
        try:
            return mlx_speech.transcribe(wav, task, timed), ""
        except Exception:
            exe = "fast" if fast_speech.available() else shutil.which("whisper")
            if not exe:
                return None, "Couldn't listen"
    if exe == "fast":
        try:
            return fast_speech.transcribe(wav, task, timed), ""
        except Exception as err:
            exe = shutil.which("whisper")
            if not exe:
                return None, f"Couldn't listen: {err}"[:300]
    out = Path(tmp) / task
    out.mkdir(exist_ok=True)
    proc = subprocess.run(
        [exe, str(wav), "--model", WHISPER_MODEL, "--task", task, "--fp16", "False",
         "--condition_on_previous_text", "False", "--output_format", "json", "--output_dir", str(out),
         "--verbose", "False", *(["--word_timestamps", "True"] if timed else [])], capture_output=True, text=True)
    result = out / f"{wav.stem}.json"
    if proc.returncode != 0 or not result.is_file():
        tail = [ln for ln in proc.stderr.splitlines() if ln.strip()]
        return None, (tail[-1] if tail else "Whisper couldn't read this clip")
    return json.loads(result.read_text()), ""


PAUSE = 0.5
SNAP = 0.25


def time_at(heard, fraction, ending=False):
    """The time a fraction of the way through the speech of the heard words, pauses between them left out. On the line
    between two words a start belongs to the next word and an end to the one before."""
    lengths = [w[2] - w[1] for w in heard]
    target, run = fraction * sum(lengths), 0.0
    for w, length in zip(heard, lengths):
        if target < run + length - 1e-6 or (ending and target <= run + length + 1e-6):
            return w[1] + (target - run)
        run += length
    return heard[-1][2]


def _speech_clock(heard):
    """Prepare cumulative speech once for all the words in a translated segment."""
    lengths = [w[2] - w[1] for w in heard]
    total = sum(lengths)
    if not math.isfinite(total) or any(length < 0 or not math.isfinite(length) for length in lengths):
        return lambda fraction, ending=False: time_at(heard, fraction, ending)
    runs, early, late, run = [], [], [], 0.0
    for length in lengths:
        runs.append(run)
        edge = run + length
        early.append(edge - 1e-6)
        late.append(edge + 1e-6)
        run = edge

    def at(fraction, ending=False):
        target = fraction * total
        if math.isnan(target):
            return heard[-1][2]
        n = bisect_left(late, target) if ending else bisect_right(early, target)
        if n == len(heard):
            return heard[-1][2]
        return heard[n][1] + (target - runs[n])
    return at


def pause_marks(heard):
    """Where the long pauses fall, as fractions of the speech."""
    total = sum(w[2] - w[1] for w in heard) or 1.0
    marks, run = [], 0.0
    for prev, nxt in zip(heard, heard[1:]):
        run += prev[2] - prev[1]
        if nxt[1] - prev[2] >= PAUSE:
            marks.append(run / total)
    return marks


def boundaries(english, heard):
    """Where each English word starts, as fractions of the speech: by word length, then pulled onto a pause in the
    original when one is close, so a sentence break stays a sentence break."""
    weights = [len(w) + 1 for w in english]
    total, run, edges = sum(weights), 0, []
    for weight in weights:
        edges.append(run / total)
        run += weight
    edges.append(1.0)
    for mark in pause_marks(heard):
        near = [n for n in range(1, len(english)) if abs(edges[n] - mark) <= SNAP]
        stops = [n for n in near if english[n - 1][-1] in ".,;:!?"]
        k = min(stops or near, key=lambda n: abs(edges[n] - mark), default=None)
        if k and edges[k - 1] < mark < edges[k + 1]:
            edges[k] = mark
    return edges


def fit_translation(heard, segments):
    """English words timed from what was actually said. Whisper times the original language well and its own translation
    badly, so each translated segment takes the words heard during it and its English words are laid along their timing."""
    if not heard or not segments:
        return []
    groups = [[] for _ in segments]
    for w in heard:
        mid = (w[1] + w[2]) / 2
        groups[min(range(len(segments)), key=lambda n: 0 if segments[n]["start"] <= mid <= segments[n]["end"]
                   else min(abs(mid - segments[n]["start"]), abs(mid - segments[n]["end"])))].append(w)
    words = []
    for seg, group in zip(segments, groups):
        english = str(seg.get("text", "")).split()
        if not english:
            continue
        span = group or [["", float(seg["start"]), float(seg["end"])]]
        edges = boundaries(english, span)
        clock = _speech_clock(span)
        for w, lo, hi in zip(english, edges, edges[1:]):
            a, b = clock(lo), clock(hi, True)
            if b > a:
                words.append([w[:40], round(a, 2), round(b, 2)])
                if len(words) >= MAX_WORDS:
                    return words
    return words


def run_transcribe(job_id, exe, src, start, end, timed=False, task="translate"):
    """Speech in the clip range, translated to English or in its own language, via the whisper command line.
    With timed set it also returns each word's time, in seconds from the start of the range. Any failure ends the job,
    because the page waits for as long as it says it is working."""
    try:
        listen(job_id, exe, src, start, end, timed, task)
    except Exception as err:
        log.exception("transcribe {job_id}")
        transcripts[job_id] = {"id": job_id, "state": "error", "message": f"Listening failed: {err}"[:300]}


def listen(job_id, exe, src, start, end, timed, task):
    def fail(message):
        transcripts[job_id] = {"id": job_id, "state": "error", "message": message[:300]}

    if task == "translate":
        said = embedded_subs.words(src, start, end)
        if said or (said is not None and not exe):
            return finish_listen(job_id, said, timed, fail)
    if not exe:
        return fail(WHISPER_HINT)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "clip.wav"
        cut = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", src,
             "-map", "0:a:0", "-ac", "1", "-ar", "16000", str(wav)], capture_output=True, text=True)
        if cut.returncode != 0 or not wav.is_file():
            return fail("This clip has no audio to listen to")
        if timed and task == "translate":
            # Time the original language, then translate separately and lay the English along that timing.
            original, problem = whisper_json(exe, wav, tmp, "transcribe", True)
            if original is None:
                return fail(problem)
            heard = spoken_words(original)
            if original.get("language") == "en":
                words = heard
            else:
                english, problem = whisper_json(exe, wav, tmp, "translate", False)
                if english is None:
                    return fail(problem)
                words = fit_translation(heard, english.get("segments", [])) or heard
        else:
            data, problem = whisper_json(exe, wav, tmp, task, timed)
            if data is None:
                return fail(problem)
            words = spoken_words(data) if timed else []
            heard_text = data.get("text", "")
    finish_listen(job_id, words if timed else heard_text, timed, fail)


def finish_listen(job_id, heard, timed, fail):
    """Ends a job with what was said: timed words, or for a plain caption the text trimmed to fit."""
    text = " ".join(w[0] for w in heard) if timed else trim_caption(" ".join(w[0] for w in heard) if isinstance(heard, list) else heard)
    if not text:
        return fail("No speech found in this clip")
    transcripts[job_id] = {"id": job_id, "state": "done", "text": text, **({"words": heard} if timed else {})}


# Speech for every clip that exists, worked out in the background when its cut is made, so captioning one is instant.
speech = {"cache": None}


def speech_cache():
    with lock:
        if speech["cache"] is None:
            speech["cache"] = SpeechCache(DATA_DIR / "speech", heard_words)
        return speech["cache"]


def heard_words(src, start, end):
    """Timed English words for a stretch of a video, [] when nobody speaks, None when listening failed."""
    exe = speech_engine()
    if not exe and not embedded_subs.has_subtitles(src):
        return None
    job_id = f"warm{hashlib.sha1(f'{src}{start}{end}'.encode()).hexdigest()[:8]}"
    listen(job_id, exe, src, start, end, True, "translate")
    result = transcripts.pop(job_id, {})
    if result.get("state") == "done":
        return result.get("words", [])
    return [] if "No speech" in result.get("message", "") else None


def warm_speech(src, start, end):
    """Queue a clip to be listened to. Does nothing without Whisper, for a clip too long to caption, or when switched off."""
    if os.environ.get("CLIPBENCH_NO_WARM") or end - start > MAX_TRANSCRIBE or not Path(src).is_file() or not (speech_engine() or embedded_subs.has_subtitles(src)):
        return
    speech_cache().queue(src, start, end)


TITLE_LIMIT = 100


def read_publish(name):
    folder = short_folder(name)
    out = {}
    for key in ("title", "description"):
        f = folder / f"{key}.txt"
        out[key] = f.read_text().strip() if f.is_file() else ""
    return out


def write_publish(name, body):
    folder = short_folder(name)
    if not (folder / "video.mp4").is_file():
        raise ValueError("Render the Short first")
    title, description = str(body.get("title", "")).strip(), str(body.get("description", "")).strip()
    if len(title) > TITLE_LIMIT:
        raise ValueError(f"The title is {len(title)} characters; YouTube allows {TITLE_LIMIT}")
    (folder / "title.txt").write_text(title + "\n")
    (folder / "description.txt").write_text(description + "\n")


def clip_options(c):
    """The timing options of a clip as make_short.py reads them."""
    return {"speed": float(c.get("speed") or 1), "ramp": c.get("ramp") or "none", "freeze": float(c.get("freeze") or 0)}


def top_length(clips):
    """Seconds the top lane lasts once its transitions have overlapped the clips."""
    top = [c for c in clips if (c.get("lane") or "top") == "top"]
    lengths = [out_length((float(c["in"]), float(c["out"])), clip_options(c)) for c in top]
    return joined_length(lengths, [(c.get("transition") or "none", float(c.get("tlen") or 0.3)) for c in top])


SNAPSHOT_DIR = DATA_DIR / "rendered"
CLIP_CACHE_DIR = DATA_DIR / "clipcache"


def rendered_project(name):
    """The project as it was when its Short was last rendered, or None for a Short rendered before this was kept."""
    try:
        return json.loads((SNAPSHOT_DIR / f"{name}.json").read_text())
    except (OSError, ValueError):
        return None


def cached_motion(vid, src):
    """The motion already measured for a video, never measuring it now."""
    cache = motion_path(vid)
    try:
        if cache.is_file() and cache.stat().st_mtime >= Path(src).stat().st_mtime:
            saved = json.loads(cache.read_text())
            return saved if saved.get("values") else None
    except (OSError, ValueError, AttributeError):
        pass
    return None


def measure_moments(project):
    """What each top-lane clip of a known video looks like in the terms suggestions are scored in, so a Short cut by hand
    can teach the ranking once it is published. Clips of videos the bench no longer knows are left out."""
    sources, moments = {}, []
    for clip in project.get("clips") or []:
        src = str(clip.get("src") or "")
        vid = video_id(src)
        if clip.get("lane", "top") != "top" or vid not in registry:
            continue
        if src not in sources:
            cues = dialogue_cues(src) or []
            wave = load_wave(vid) or {}
            peaks, per_sec = wave.get("peaks", []), wave.get("per_sec", WAVE_PER_SEC)
            cache = scene_path(vid)
            scenes = read_scenes(cache) if cache.is_file() else []
            duration = (probe(src) or {}).get("duration") or max([c[1] for c in cues] + [float(clip["out"])])
            kind = clip_profile.profile(cues, duration, scenes, peaks, per_sec)
            sources[src] = (cues, duration, scenes, peaks, per_sec, kind, cached_motion(vid, src))
        cues, duration, scenes, peaks, per_sec, kind, motion = sources[src]
        moment = suggest.describe(float(clip["in"]), float(clip["out"]), cues, duration, scenes, peaks, per_sec, kind, motion)
        moments.append({**moment, "src": src})
    return moments


def describe_render(name, project):
    """Add to a render's snapshot the moment each of its clips is, measured while the sources are still here. Best effort:
    a snapshot that cannot be measured is left as it was."""
    try:
        moments = measure_moments(project)
        path = SNAPSHOT_DIR / f"{name}.json"
        saved = json.loads(path.read_text())
        path.write_text(json.dumps({**saved, "moments": moments}))
    except Exception as err:
        log.exception("moments of %s could not be measured", name)


def start_render(name, project):
    with lock:
        if renders.get(name, {}).get("state") == "working":
            return renders[name]
        total = top_length(rendered_clips(project))
        renders[name] = {"state": "working", "pct": 0, "message": "Starting", "total": total}
    try:
        export_cuts(name, project)
        folder = short_folder(name)
        folder.mkdir(exist_ok=True)
        flags = render_flags(project) + export_audio(name, project)
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        (SNAPSHOT_DIR / f"{name}.json").write_text(json.dumps(project))
    except (ValueError, KeyError, TypeError, OSError) as err:
        renders[name] = {"state": "error", "message": str(err)}
        return renders[name]
    threading.Thread(target=run_render, args=(name, project.get("hook") or "", folder, flags), daemon=True).start()
    threading.Thread(target=describe_render, args=(name, project), daemon=True).start()
    return renders[name]


PREVIEW_DIR = DATA_DIR / "preview"
CAP_CARRY = (("capX", "capY"), ("capScale",), ("capRot",), ("capLook",), ("capHi",))


def preview_key(name):
    return f"{name}~clip"


def preview_clip(project, index):
    """One clip of the project as a Short of its own: alone in the top lane, with the caption position, size and look
    it would have inherited from the top lane clips before it."""
    clips = project.get("clips", [])
    if not isinstance(index, int) or not 0 <= index < len(clips):
        raise ValueError("Pick a clip first")
    chosen = {}
    for n, c in enumerate(clips[:index + 1]):
        if n != index and (c.get("lane") or "top") != "top":
            continue
        for group in CAP_CARRY:
            if all(c.get(k) is not None for k in group):
                chosen.update({k: c[k] for k in group})
    clip = {**clips[index], **chosen, "lane": "top", "transition": "none"}
    return {**project, "template": "full", "clips": [clip], "audio": []}


def preview_path(name):
    return PREVIEW_DIR / f"{name}.mp4"


_preview_results = OrderedDict()
PREVIEW_CACHE_LIMIT = 32


def preview_signature(sub):
    """Version every external input as well as the selected clip's effective settings."""
    clip = sub["clips"][0]
    source = str(clip["src"])
    src = Path(source)
    paths = [src]
    if not src.is_file():
        saved = indexed_cut(source, float(clip["in"]), float(clip["out"]))
        if saved:
            paths.append(cut_path(saved))
    if clip.get("voice") and src.is_file():
        paths.append(voice_isolation.cached_path(VOICE_DIR, source, *rounded_range(clip["in"], clip["out"])))
    paths += [AVATAR_FILE, ROOT / "scripts/make_short.py",
              ROOT / "scripts/tracking.py", Path(FONT_IMPACT), Path(FONT_BOLD), Path(FONT_REGULAR), Path(FONT_EMOJI)]
    # Timeline annotations and edit protection do not enter the rendered picture
    # or soundtrack. Keep them from invalidating an otherwise reusable preview.
    settings = {k: v for k, v in sub.items() if k not in ("bank", "other", "markers", "laneName", "laneLock")}
    return (hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest(),
            tuple((str(path), _wave_cache_stamp(path)) for path in paths))


def run_preview(name, sub, signature, flags):
    key = preview_key(name)
    run_render(key, sub.get("hook") or "", PREVIEW_DIR, flags,
               PREVIEW_DIR / f"{name}.cuts.txt", preview_path(name))
    result = renders.get(key, {})
    if result.get("state") != "done":
        return
    # Files can be replaced during a render. Such results must never become cache hits.
    if preview_signature(sub) != signature:
        return
    output_stamp = _wave_cache_stamp(preview_path(name))
    if output_stamp is not None:
        with lock:
            if renders.get(key) is not result:
                return
            _preview_results[name] = (signature, output_stamp, dict(result))
            _preview_results.move_to_end(name)
            while len(_preview_results) > PREVIEW_CACHE_LIMIT:
                _preview_results.popitem(last=False)


def start_preview(name, project, index):
    key = preview_key(name)
    with lock:
        if renders.get(key, {}).get("state") == "working":
            return renders[key]
    sub = preview_clip(project, index)
    signature = preview_signature(sub)
    with lock:
        if renders.get(key, {}).get("state") == "working":
            return renders[key]
        cached = _preview_results.get(name)
        if cached and cached[:2] == (signature, _wave_cache_stamp(preview_path(name))):
            _preview_results.move_to_end(name)
            renders[key] = dict(cached[2])
            return renders[key]
        _preview_results.pop(name, None)
        renders[key] = {"state": "working", "pct": 0, "message": "Starting", "total": top_length(sub["clips"])}
    try:
        export_cuts(name, sub, PREVIEW_DIR)
        flags = render_flags(sub) + ["--draft"]
    except (ValueError, KeyError, TypeError, OSError) as err:
        renders[key] = {"state": "error", "message": str(err)}
        return renders[key]
    threading.Thread(target=run_preview, args=(name, sub, signature, flags), daemon=True).start()
    return renders[key]


def export_audio(name, project):
    """Write the project's sounds next to its cut list and return the flag that points the render at them."""
    items, target = audio_mix_items(project), PROJECT_DIR / f"{name}.audio.json"
    if not items:
        target.unlink(missing_ok=True)
        return []
    target.write_text(json.dumps(items))
    return ["--audio-mix", str(target)]


def run_render(name, hook, folder, flags, cuts=None, out=None):
    out = out or folder / "video.mp4"
    cmd = [sys.executable, str(ROOT / "scripts" / "make_short.py"), "--cuts", str(cuts or PROJECT_DIR / f"{name}.cuts.txt"),
           "--card", *flags, f"--text={hook}", "--cache", str(CLIP_CACHE_DIR), "-o", str(out)]
    total = renders[name]["total"] or 1
    tail = ""
    render_log = logging.getLogger("clipbench.render")
    render_log.info("%s: rendering to %s", name, out)
    began = time.monotonic()
    try:
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace")
        buf = ""
        while chunk := proc.stderr.read(256):
            buf = (buf + chunk)[-2000:]
            tail = buf
            hits = RENDER_TIME_RE.findall(buf)
            if hits:
                h, m, s = hits[-1]
                done = int(h) * 3600 + int(m) * 60 + float(s)
                pct = max(renders[name]["pct"], min(99, round(done / total * 100)))
                renders[name] = {**renders[name], "pct": pct, "message": "Rendering"}
        code = proc.wait()
    except OSError as err:
        render_log.exception("%s: couldn't start the render", name)
        renders[name] = {"state": "error", "message": f"Couldn't start the render: {err}"}
        return
    if code == 0 and out.is_file():
        render_log.info("%s: done in %.0fs, %d bytes", name, time.monotonic() - began, out.stat().st_size)
        renders[name] = {"state": "done", "pct": 100, "message": "Done", "folder": str(folder.relative_to(ROOT)) if folder.is_relative_to(ROOT) else str(folder),
                         "size": out.stat().st_size, "stamp": int(out.stat().st_mtime)}
        return
    lines = [ln.strip() for ln in tail.replace("\r", "\n").split("\n") if ln.strip()]
    render_log.error("%s: render failed with code %s after %.0fs\n%s", name, code, time.monotonic() - began, "\n".join(lines[-12:]))
    renders[name] = {"state": "error", "message": (lines[-1] if lines else "The render failed")[:300]}


DOWNLOAD_DIR = WORKSPACE / "clips"
MAX_DOWNLOAD = "2G"
downloads = {}
PROGRESS_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")
INSTALL_HINT = "yt-dlp isn't installed. In Terminal run: brew install yt-dlp"


def valid_url(text):
    parts = urlparse(text)
    return parts.scheme in ("http", "https") and bool(parts.netloc) and not re.search(r"\s", text) and len(text) < 2000


MAX_SECTION = 600


def section_args(start, end):
    """yt-dlp flags that fetch only start..end seconds of a video, and the tag that keeps the file name unique."""
    return ["--download-sections", f"*{start:.2f}-{end:.2f}", "--force-keyframes-at-cuts"], f"-{round(start)}-{round(end)}"


HLS_LIVE_FORMAT = "bestvideo[protocol*=m3u8][height<=1080]+bestaudio[protocol*=m3u8]/best[protocol*=m3u8]"
EXTINF_RE = re.compile(r"#EXTINF:([\d.]+)")
WHITELIST = "file,http,https,tcp,tls,crypto"


def playlist_length(text):
    return sum(float(x) for x in EXTINF_RE.findall(text))


def live_window(total, ago_start, ago_end):
    """Where a stretch of a live stream sits in its playlist, given how many seconds ago each end happened. The playlist
    ends at the live edge. Raises ValueError when the stretch has left the part of the stream that is kept."""
    start, end = total - ago_start, total - ago_end
    if end <= start:
        raise ValueError("Mark the out after the in")
    if start < 0:
        raise ValueError(f"That moment has left the stream's buffer, which holds about {round(total / 60)} minutes. Mark it again")
    return start, end - start


def fetch_text(url):
    """The text at a link, through curl because the Python that ships with macOS can't verify certificates."""
    got = subprocess.run(["curl", "-sfL", "--max-time", "30", "--", url], capture_output=True, text=True)
    if got.returncode:
        raise ValueError("Couldn't read the stream's playlist")
    return got.stdout


def live_playlists(exe, url, tmp):
    """The closed playlists (video, then audio) of a live stream's recent buffer in tmp, and how many seconds they hold."""
    got = subprocess.run([exe, "--no-playlist", "--no-warnings", "-g", "-f", HLS_LIVE_FORMAT, "--", url],
                         capture_output=True, text=True, timeout=90)
    urls = got.stdout.split()
    if got.returncode or not urls:
        raise ValueError("Couldn't read this live stream")
    lists, total, fetched = [], None, time.time()
    for n, u in enumerate(urls):
        text = fetch_text(u)
        fetched = time.time()
        length = playlist_length(text)
        if not length:
            raise ValueError("This stream has no recorded buffer to clip from")
        total = length if total is None else min(total, length)
        path = Path(tmp) / f"{n}.m3u8"
        path.write_text(text if "#EXT-X-ENDLIST" in text else text.rstrip() + "\n#EXT-X-ENDLIST\n")
        lists.append(path)
    return lists, total, fetched


def record_call(path, body):
    """The reply and status for starting or stopping the recording of a live Twitch channel."""
    if path == "/api/live-record/stop":
        recorder.stop()
        return {"ok": True}, 200
    url = str(body.get("url", "")).strip()
    if not any(s["url"] == url for s in streamers.load(STREAMER_FILE)) and not re.fullmatch(r"https://www\.twitch\.tv/[A-Za-z0-9_]{2,25}", url):
        return {"error": "Only a Twitch channel can be recorded"}, 400
    exe, ffmpeg = shutil.which("yt-dlp"), shutil.which("ffmpeg")
    if not exe or not ffmpeg:
        return {"error": INSTALL_HINT if not exe else "ffmpeg isn't installed"}, 400
    try:
        return {"started": recorder.start(exe, ffmpeg, url)}, 200
    except ValueError as err:
        return {"error": str(err)}, 400


def streamer_call(path, body):
    """The reply and status for the Streamers panel's calls: add, remove, and whether one channel is live."""
    try:
        if path == "/api/streamers":
            return streamers.add(STREAMER_FILE, body.get("input", "")), 200
        if path == "/api/streamers/remove":
            return streamers.remove(STREAMER_FILE, body.get("url", "")), 200
        url = str(body.get("url", ""))
        if not any(s["url"] == url for s in streamers.load(STREAMER_FILE)):
            return {"error": "That channel isn't in your list"}, 400
        exe = shutil.which("yt-dlp")
        if not exe:
            return {"error": INSTALL_HINT}, 400
        return streamers.check_live(exe, url), 200
    except ValueError as err:
        return {"error": str(err)}, 400


def live_buffer(url):
    exe = shutil.which("yt-dlp")
    if not exe:
        raise ValueError(INSTALL_HINT)
    with tempfile.TemporaryDirectory() as tmp:
        return live_playlists(exe, url, tmp)[1]


def live_tag(title, started):
    """A readable file name for a clip cut from a stream: its title and the local time the clip starts."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_")[:40] or "stream"
    return f"{slug}-{time.strftime('%H%M%S', time.localtime(started))}"


def free_path(folder, stem, ext):
    path, n = folder / f"{stem}{ext}", 2
    while path.exists():
        path = folder / f"{stem}-{n}{ext}"
        n += 1
    return path


def run_live_cut(job_id, exe, url, wall, tag):
    """Cuts a stretch out of a live stream's recent buffer: its playlists are closed so ffmpeg can seek in them."""
    ffmpeg = shutil.which("ffmpeg")
    patch = lambda **kw: downloads.__setitem__(job_id, {**downloads[job_id], **kw})
    try:
        if not ffmpeg:
            raise ValueError("ffmpeg isn't installed")
        with tempfile.TemporaryDirectory() as tmp:
            lists, total, fetched = live_playlists(exe, url, tmp)
            patch(message="Reading the stream", pct=10)
            offset, length = live_window(total, fetched - wall[0], fetched - wall[1])
            DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
            out = free_path(DOWNLOAD_DIR, tag, ".mp4")
            cmd = [ffmpeg, "-v", "error", "-y"]
            for path in lists:
                cmd += ["-protocol_whitelist", WHITELIST, "-ss", f"{offset:.2f}", "-i", str(path)]
            cmd += ["-t", f"{length:.2f}", "-map", "0:v:0", "-map", f"{len(lists) - 1}:a:0",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-pix_fmt", "yuv420p", str(out)]
            patch(message="Cutting", pct=40)
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if done.returncode or not out.is_file():
                raise ValueError((done.stderr.strip().splitlines() or ["The cut failed"])[-1][:300])
            if not playable(out, length):
                out.unlink(missing_ok=True)
                raise ValueError("The cut came back empty. Mark the moment again")
        patch(state="done", pct=100, message="Downloaded", file=str(out))
    except (ValueError, OSError, subprocess.SubprocessError) as err:
        patch(state="error", message=str(err)[:300])


def run_recorded_cut(job_id, path, started, wall, tag):
    """Cuts a stretch out of the recording of a live stream that keeps no history of its own."""
    ffmpeg = shutil.which("ffmpeg")
    patch = lambda **kw: downloads.__setitem__(job_id, {**downloads[job_id], **kw})
    try:
        if not ffmpeg:
            raise ValueError("ffmpeg isn't installed")
        offset, length = liverec.window(started, wall[0], wall[1], time.time())
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        out = free_path(DOWNLOAD_DIR, tag, ".mp4")
        patch(message="Cutting", pct=30)
        cmd = [ffmpeg, "-v", "error", "-y", "-ss", f"{offset:.2f}", "-i", str(path), "-t", f"{length:.2f}", "-map", "0:v:0", "-map", "0:a:0?",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-pix_fmt", "yuv420p", str(out)]
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if done.returncode or not out.is_file():
            raise ValueError((done.stderr.strip().splitlines() or ["The cut failed"])[-1][:300])
        if not playable(out, length):
            out.unlink(missing_ok=True)
            raise ValueError("The cut came back empty. Mark the moment again")
        patch(state="done", pct=100, message="Downloaded", file=str(out))
    except (ValueError, OSError, subprocess.SubprocessError) as err:
        patch(state="error", message=str(err)[:300])


def start_download(url, section=None, live_wall=None, title="", project=None):
    exe = shutil.which("yt-dlp")
    if not exe:
        return {"state": "error", "pct": 0, "message": INSTALL_HINT}
    job = {"id": hashlib.sha1(f"{url}{time.time()}".encode()).hexdigest()[:12], "state": "working", "pct": 0,
           "message": "Starting"}
    downloads[job["id"]] = job
    recording = recorder.active(url) if live_wall else None
    if recording:
        args = (run_recorded_cut, job["id"], recording[0], recording[1], live_wall, live_tag(title, live_wall[0]))
    elif live_wall:
        args = (run_live_cut, job["id"], exe, url, live_wall, live_tag(title, live_wall[0]))
    else:
        args = (run_download, job["id"], exe, url, section)
    threading.Thread(target=functools.partial(guarded_download, project=project), args=args, daemon=True).start()
    return job


def guarded_download(run, job_id, *args, project=None):
    """Run a download so that any failure, such as another download's temporary file vanishing mid-scan, ends the job
    in an error the page can show instead of leaving it working forever. The video it makes belongs to the project."""
    try:
        run(job_id, *args)
        if project and downloads[job_id].get("state") == "done" and downloads[job_id].get("file"):
            store.claim_video(downloads[job_id]["file"], project)
        if downloads[job_id].get("state") == "done" and downloads[job_id].get("file"):
            prepare_after_download(downloads[job_id]["file"])
    except Exception as err:
        log.exception("download {job_id}")
        downloads[job_id] = {**downloads[job_id], "state": "error", "message": f"The download failed: {err}"[:300]}


EMPTY_CUT = ("The download came back empty or cut short. A stream that just ended can't be cut until YouTube finishes "
             "processing it, so try again later or download the whole video")


def playable(path, want=0.0):
    """True when the file has a picture and at least half the length asked for. yt-dlp can finish without an error and
    leave an empty or truncated file, as it does for a stream YouTube is still processing."""
    meta = probe(path)
    return bool(meta and meta["video"] and meta["duration"] > 0 and meta["duration"] >= want * 0.5)


def downloaded_file(line):
    """True when a line of yt-dlp output is the path of a finished video in the download folder."""
    if not line.startswith("/"):
        return False
    path = Path(line)
    return path.parent == DOWNLOAD_DIR and path.suffix.lower() in VIDEO_EXTS and path.is_file()


def run_download(job_id, exe, url, section=None):
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    started = time.time() - 1
    flags, tag = section_args(*section) if section else ([], "")
    cmd = [exe, "--no-playlist", "--no-quiet", "--progress", "--newline", "--restrict-filenames", "--no-mtime",
           "--print", "after_move:filepath",
           "--max-filesize", MAX_DOWNLOAD, "-S", "res:1080,vcodec:h264,acodec:aac", "--merge-output-format", "mp4", *flags,
           "-o", str(DOWNLOAD_DIR / f"%(title).60B-%(id)s{tag}.%(ext)s"), "--", url]
    tail, printed = [], None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        for line in proc.stdout:
            line = line.strip()
            tail = (tail + [line])[-6:]
            if m := PROGRESS_RE.search(line):
                downloads[job_id] = {**downloads[job_id], "pct": min(99, round(float(m.group(1)))), "message": "Downloading"}
            elif downloaded_file(line):
                printed = Path(line)
        code = proc.wait()
    except OSError as err:
        downloads[job_id] = {**downloads[job_id], "state": "error", "message": f"Couldn't start yt-dlp: {err}"}
        return
    # yt-dlp prints the finished file's path; a file already downloaded before is printed too. Fall back to the newest file.
    fresh = [printed] if printed else [
        p for p in DOWNLOAD_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS and not p.name.startswith(".") and p.stat().st_mtime >= started]
    if code == 0 and fresh:
        newest = max(fresh, key=lambda p: p.stat().st_mtime)
        if not playable(newest, section[1] - section[0] if section else 0):
            newest.unlink(missing_ok=True)
            downloads[job_id] = {**downloads[job_id], "state": "error", "message": EMPTY_CUT}
            return
        downloads[job_id] = {**downloads[job_id], "state": "done", "pct": 100, "message": "Downloaded", "file": str(newest)}
        return
    errors = [t for t in tail if t.startswith("ERROR")]
    downloads[job_id] = {**downloads[job_id], "state": "error",
                         "message": (errors[-1] if errors else "The download didn't finish")[:300]}


MAX_UPLOAD = 8 * 1024 ** 3
UPLOAD_CHUNK = 1024 * 1024


def upload_target(name, exts=None, folder=None):
    """A free path in clips/ (or the given folder) for a dropped file, keeping its name where it is safe. None if
    it isn't one of the allowed kinds, videos unless exts says otherwise."""
    exts, folder = exts or VIDEO_EXTS, folder or DOWNLOAD_DIR
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(name).stem).strip(" .") or "file"
    ext = Path(name).suffix.lower()
    if ext not in exts:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    target, n = folder / f"{stem[:120]}{ext}", 2
    while target.exists():
        target = folder / f"{stem[:120]}-{n}{ext}"
        n += 1
    return target


_audio_lengths = {}
_pending_audio_lengths = {}
audio_registry = {}


def audio_duration(path):
    """Cache duration by file version and share concurrent ffprobe work."""
    stat = Path(path).stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
    with lock:
        if key in _audio_lengths:
            length = _audio_lengths.pop(key)
            _audio_lengths[key] = length
            return length
        pending = _pending_audio_lengths.get(key)
        owner = pending is None
        if owner:
            pending = _pending_audio_lengths[key] = Future()
    if not owner:
        return pending.result()
    try:
        try:
            length = probe_duration(str(path))
        except (subprocess.CalledProcessError, ValueError, OSError):
            length = None
        with lock:
            _remember_metadata(_audio_lengths, key, length)
        pending.set_result(length)
        return length
    except BaseException as exc:
        pending.set_exception(exc)
        raise
    finally:
        with lock:
            _pending_audio_lengths.pop(key, None)


def scan_audio():
    """Songs and sound effects in audio/ and music/, shortest first within each kind."""
    items = []
    for d in AUDIO_DIRS:
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.name.startswith(".") or p.suffix.lower() not in AUDIO_EXTS or not p.is_file():
                continue
            length = audio_duration(p)
            if not length:
                continue
            vid = video_id(p)
            audio_registry[vid] = p
            items.append({"id": vid, "name": p.stem, "path": str(p), "duration": round(length, 2),
                          "kind": "sfx" if length <= SFX_MAX_SECONDS else "song"})
    return items


def audio_mix_items(project):
    """The project's songs and sound effects as make_short.py reads them, checked against the audio library."""
    wanted = project.get("audio") or []
    if not isinstance(wanted, list) or len(wanted) > MAX_AUDIO_ITEMS:
        raise ValueError(f"A Short can hold up to {MAX_AUDIO_ITEMS} sounds")
    if wanted:
        scan_audio()
    items = []
    for n, a in enumerate(wanted, 1):
        path = audio_registry.get(str(a.get("file", "")))
        if path is None or not path.is_file():
            raise ValueError(f"Sound {n} is missing from the audio library")
        items.append({"path": str(path), "start": float(a.get("start") or 0), "in": float(a.get("in") or 0),
                      "dur": float(a.get("dur") or 0), "volume": float(a.get("volume", 1)),
                      "volumeend": float(a.get("volumeEnd") if a.get("volumeEnd") is not None else a.get("volume", 1)),
                      "fadein": float(a.get("fadeIn") or 0), "fadeout": float(a.get("fadeOut") or 0)})
    return items


def extra_paths():
    return [Path(p) for p in store.list_extra_videos()]


PROJECT_NAME = re.compile(r"[A-Za-z0-9_-]{1,60}")


def project_arg(query):
    """The project a request is made for, from its query string or None. Raises ValueError for a name that isn't one."""
    name = query.get("project", [""])[0]
    if name and not PROJECT_NAME.fullmatch(name):
        raise ValueError("That isn't a project name")
    return name or None


def scan_library(project=None):
    """Every video the bench knows, and with a project only the ones it can see: its own and, unless it keeps its own media, the shared ones nobody claimed."""
    found = {}
    for d in LIBRARY_DIRS:
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if not p.name.startswith(".") and p.suffix.lower() in VIDEO_EXTS and p.is_file():
                    found[video_id(p)] = p
    imported = extra_paths()
    extras = set(imported)
    for p in imported:
        if p.is_file():
            found[video_id(p)] = p
    with lock:
        registry.update(found)
    items = []
    owners = store.video_owners() if project else {}
    own_only = bool(project) and store.own_media(project)
    broll_root, library_roots = None, None
    for vid, p in found.items():
        if project and ((str(p) in owners and project not in owners[str(p)]) or (own_only and str(p) not in owners)):
            continue
        meta = probe(p)
        if not meta:
            continue
        direct = plays_directly(p, meta)
        # Resolve shared roots once per scan; keep symlink changes visible on
        # the next scan and share each file's parents between classifications.
        if broll_root is None:
            broll_root = BROLL_DIR.resolve()
        parents = p.resolve().parents
        if p in extras and library_roots is None:
            library_roots = tuple(d.resolve() for d in LIBRARY_DIRS)
        managed = p not in extras or any(d in parents for d in library_roots)
        items.append({"id": vid, "name": p.name, "path": str(p), "duration": meta["duration"],
                      "w": meta["width"], "h": meta["height"], "direct": direct,
                      "broll": broll_root in parents, "remove": "trash" if managed else "unlist", "ready": direct or proxy_path(vid).is_file()})
    return items


TRASH_DIR = Path.home() / ".Trash"


def is_broll(path):
    """Footage added through the B-roll panel, kept apart from the sources clips are cut from."""
    return BROLL_DIR.resolve() in path.resolve().parents


def in_library_dir(path):
    resolved = path.resolve()
    return any(d.resolve() in resolved.parents for d in LIBRARY_DIRS)


def save_clips_of(path, timeout=300):
    """Make sure every clip cut from this video exists as its own file, so the clips outlive the video."""
    jobs = []
    for src, start, end in all_clip_ranges():
        # A clip with no length or an impossible range has nothing to save, so it never holds the video back.
        if Path(src) == path and 0 <= start < end <= start + MAX_CUT_SECONDS:
            jobs.append(start_cut(src, start, end))
    deadline = time.time() + timeout
    for job in jobs:
        while cut_status(job["id"])["state"] == "working" and time.time() < deadline:
            time.sleep(0.2)
        if cut_status(job["id"])["state"] != "ready":
            raise ValueError("Couldn't save every clip cut from this video, so it was left in place")


def remove_video(vid):
    """Take a video out of the library. A file that lives in the clips folder goes to the Trash with its previews;
    a video that was added by path is only unlisted, and the file stays where it is."""
    with lock:
        path = registry.get(vid)
    if not path:
        raise ValueError("That video isn't in the library")
    save_clips_of(path)
    if path in extra_paths() and not in_library_dir(path):
        store.remove_extra_video(path)
        how = "unlisted"
    else:
        if not in_library_dir(path) or not path.is_file():
            raise ValueError("That file isn't in the clips folder")
        TRASH_DIR.mkdir(exist_ok=True)
        target = TRASH_DIR / path.name
        if target.exists():
            target = TRASH_DIR / f"{path.stem} {int(time.time())}{path.suffix}"
        shutil.move(str(path), str(target))
        store.remove_extra_video(path)
        how = "trash"
    store.unclaim_video(path)
    for leftover in PROXY_DIR.glob(f"{vid}.*"):
        leftover.unlink(missing_ok=True)
    with lock:
        registry.pop(vid, None)
        proxies.pop(vid, None)
    return how


CUT_DIR = WORKSPACE / "clips" / ".cuts"
MAX_CUT_SECONDS = 900
CUT_PRUNE_DAYS = 7
cuts = {}
cut_slots = threading.Semaphore(2)
cut_finished = threading.Condition()
warm_lock = threading.Lock()


def cut_id(src, start, end):
    stat = Path(src).stat()
    key = f"{src}|{stat.st_size}|{stat.st_mtime_ns}|{start:.3f}|{end:.3f}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def cut_path(cid):
    return CUT_DIR / f"{cid}.mp4"


# Which saved file holds which clip, kept beside the files so a clip can be found without its source video.
def _range_key(src, start, end):
    return f"{src}|{start:.3f}|{end:.3f}"


_cut_index_cache = None


def _read_index():
    # Callers hold lock; retain only the current file version, including its directory.
    global _cut_index_cache
    path = CUT_DIR / "index.json"
    try:
        stat = path.stat()
        stamp = (path, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if _cut_index_cache is not None and _cut_index_cache[0] == stamp:
            return _cut_index_cache[1]
        index = json.loads(path.read_text())
        if not isinstance(index, dict):
            return {}
        _cut_index_cache = (stamp, index)
        return index
    except (OSError, ValueError):
        _cut_index_cache = None
        return {}


def remember_cut(src, start, end, cid):
    with lock:
        index = _read_index()
        key = _range_key(src, start, end)
        if index.get(key) == cid:
            return
        CUT_DIR.mkdir(parents=True, exist_ok=True)
        temp = CUT_DIR / "index.json.part"
        temp.write_text(json.dumps({**index, key: cid}))
        temp.replace(CUT_DIR / "index.json")


def indexed_cut(src, start, end):
    """The id of the saved file for this clip, or None when it was never saved."""
    with lock:
        cid = _read_index().get(_range_key(src, start, end))
    return cid if cid and cut_path(cid).is_file() else None


def start_cut(src, start, end):
    """Save one clip as its own small file, so playing it never has to seek inside the whole source."""
    saved = indexed_cut(src, start, end)
    if saved:
        warm_speech(src, start, end)
        return {"id": saved, "state": "ready"}
    with lock:
        known = Path(src) in registry.values()
    if not known:
        raise ValueError("That video isn't in the library")
    if not (0 <= start < end) or end - start > MAX_CUT_SECONDS:
        raise ValueError("That clip's range isn't valid")
    cid = cut_id(src, start, end)
    with lock:
        ready = cut_path(cid).is_file()
    if ready:
        remember_cut(src, start, end, cid)
        warm_speech(src, start, end)
        return {"id": cid, "state": "ready"}
    with lock:
        if cuts.get(cid, {}).get("state") == "working":
            return cuts[cid]
        cuts[cid] = {"id": cid, "state": "working"}
    threading.Thread(target=run_cut, args=(cid, src, start, end), daemon=True).start()
    return cuts[cid]


def run_cut(cid, src, start, end):
    CUT_DIR.mkdir(parents=True, exist_ok=True)
    part = CUT_DIR / f"{cid}.part.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", src, "-t", f"{end - start:.3f}",
           "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
           "-g", "30", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(part)]
    try:
        with cut_slots:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        problem = "" if proc.returncode == 0 and part.is_file() else (proc.stderr or "ffmpeg failed").strip()[-200:]
    except OSError as err:
        problem = f"Couldn't start ffmpeg: {err}"
    if problem:
        part.unlink(missing_ok=True)
        with lock:
            cuts[cid] = {"id": cid, "state": "error", "message": problem}
        with cut_finished:
            cut_finished.notify_all()
        return
    part.replace(cut_path(cid))
    remember_cut(src, start, end, cid)
    with lock:
        cuts[cid] = {"id": cid, "state": "ready"}
    with cut_finished:
        cut_finished.notify_all()
    warm_speech(src, start, end)


def cut_status(cid):
    if cut_path(cid).is_file():
        return {"id": cid, "state": "ready"}
    with lock:
        return cuts.get(cid) or {"id": cid, "state": "missing"}


warming = {"ids": []}


def all_clip_ranges():
    """Every (source, start, end) any project or Saved clip uses, once each."""
    seen, found = set(), []
    clips = []
    for project in store.iter_projects():
        project = project or {}
        clips += project.get("clips", []) + project.get("bank", [])
    for c in clips + store.list_favorites():
        try:
            key = (str(c["src"]), round(float(c["in"]), 3), round(float(c["out"]), 3))
        except (KeyError, TypeError, ValueError):
            continue
        if key not in seen:
            seen.add(key)
            found.append(key)
    return found


def warm_cuts():
    """Warm one saved clip at a time, leaving conversion capacity for editing."""
    if not warm_lock.acquire(blocking=False):
        return
    try:
        scan_library()
        pending = []
        for src, start, end in all_clip_ranges():
            try:
                cid = indexed_cut(src, start, end) or cut_id(src, start, end)
            except (ValueError, OSError):
                continue
            pending.append((cid, src, start, end))
        with lock:
            warming["ids"] = [cid for cid, *_ in pending]
        for cid, src, start, end in pending:
            try:
                job = start_cut(src, start, end)
            except (ValueError, OSError):
                with lock:
                    warming["ids"] = [i for i in warming["ids"] if i != cid]
                continue
            with cut_finished:
                while cut_status(job["id"])["state"] == "working":
                    cut_finished.wait(timeout=1)
    finally:
        warm_lock.release()


def warm_progress():
    with lock:
        ids = list(warming["ids"])
    done = sum(1 for cid in ids if cut_status(cid)["state"] in ("ready", "error"))
    return {"total": len(ids), "done": done}


def prune_cuts():
    """Forget old clip files no project or Saved clip uses any more. A clip someone still uses is never removed,
    because for a clip whose source is gone, its saved file is all that is left."""
    if not CUT_DIR.is_dir():
        return
    cutoff = time.time() - CUT_PRUNE_DAYS * 86400
    with lock:
        index = _read_index()
    in_use = {index.get(_range_key(*r)) for r in all_clip_ranges()}
    for f in CUT_DIR.iterdir():
        if f.name.endswith(".part.mp4"):
            f.unlink(missing_ok=True)
        elif f.suffix == ".mp4" and f.stem not in in_use and f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


proxy_finished = threading.Condition()


def set_proxy_status(vid, state):
    with proxy_finished:
        proxies[vid] = state
        if state["state"] != "working":
            proxy_finished.notify_all()


def proxy_status(vid, wait=False):
    """Optionally wait for completion, returning progress at least once a second."""
    with proxy_finished:
        if wait:
            proxy_finished.wait_for(lambda: proxies.get(vid, {}).get("state") != "working", timeout=1)
        return proxies.get(vid) or {"state": "none", "pct": 0}


def start_proxy(vid):
    path = registry.get(vid)
    if not path:
        return {"state": "error", "message": "unknown video"}
    with lock:
        state = proxies.get(vid)
        if state and state["state"] == "working":
            return state
        if proxy_path(vid).is_file():
            proxies[vid] = {"state": "ready", "pct": 100}
            return proxies[vid]
        proxies[vid] = {"state": "working", "pct": 0}
    threading.Thread(target=run_proxy, args=(vid, path), daemon=True).start()
    return proxies[vid]


def run_proxy(vid, path):
    PROXY_DIR.mkdir(parents=True, exist_ok=True)
    meta = probe(path) or {"duration": 0}
    tmp = PROXY_DIR / f"{vid}.part.mp4"
    base = ["ffmpeg", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats", "-i", str(path),
            "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", "-map_chapters", "-1"]
    encode = ["-vf", "scale=-2:540", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-g", "15",
              "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k"]
    # Some sources only need a browser-compatible container. Copy their streams
    # instead of encoding the entire video, with the established encode as fallback.
    compatible = (meta.get("video") == "h264" and meta.get("pixel_format") == "yuv420p"
                  and meta.get("audio") in (None, "aac", "mp3"))
    attempts = [["-c", "copy"], encode] if compatible else [encode]
    for options in attempts:
        cmd = base + options + ["-movflags", "+faststart", str(tmp)]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except OSError as err:
            set_proxy_status(vid, {"state": "error", "pct": 0, "message": f"Couldn't start ffmpeg: {err}"})
            return
        for line in proc.stdout:
            if line.startswith("out_time_ms=") and meta["duration"]:
                try:
                    done = int(line.split("=")[1]) / 1_000_000
                except ValueError:
                    continue
                set_proxy_status(vid, {"state": "working", "pct": min(99, round(done / meta["duration"] * 100))})
        err = proc.stderr.read()
        proc.stdout.close()
        proc.stderr.close()
        if proc.wait() == 0:
            tmp.replace(proxy_path(vid))
            set_proxy_status(vid, {"state": "ready", "pct": 100})
            return
        tmp.unlink(missing_ok=True)
    set_proxy_status(vid, {"state": "error", "pct": 0, "message": err.strip()[-300:]})


def fmt_time(seconds):
    return f"{seconds:.2f}"


FRAME_NAMES = ("wide", "square", "tall")
EFFECT_NAMES = ("none", "zoom_in", "zoom_out", "punch", "shake", "flash", "bw", "vignette", "glitch")


def render_flags(project):
    """Extra make_short.py flags for the project's frame shape and loudness matching."""
    flags = []
    frame = project.get("frame") or "auto"
    if frame != "auto":
        if frame not in FRAME_NAMES:
            raise ValueError("unknown frame shape")
        flags += ["--frame", frame]
    fmt, template = project.get("format") or DEFAULT_FORMAT, project.get("template") or "full"
    if fmt not in FORMATS:
        raise ValueError("unknown format")
    if template not in TEMPLATES:
        raise ValueError("unknown template")
    if fmt != DEFAULT_FORMAT:
        flags += ["--format", fmt]
    if template != "full":
        flags += ["--template", template]
        for key, flag in (("rowSplit", "--row-split"), ("colSplit", "--col-split")):
            frac = float(project.get(key) or 0.5)
            if not SPLIT_RANGE[0] <= frac <= SPLIT_RANGE[1]:
                raise ValueError(f"{key} must be between {SPLIT_RANGE[0]:g} and {SPLIT_RANGE[1]:g}")
            if frac != 0.5:
                flags += [flag, f"{frac:.3f}"]
    size = project.get("capSize") or None
    if size is not None:
        if not CAPTION_SIZES[0] <= int(size) <= CAPTION_SIZES[1]:
            raise ValueError(f"caption size must be {CAPTION_SIZES[0]} to {CAPTION_SIZES[1]}")
        if int(size) != SUB_FONT_SIZE:
            flags += ["--caption-size", str(int(size))]
    layout = project.get("layout") or "title"
    if layout not in LAYOUTS:
        raise ValueError("unknown layout")
    flags += ["--layout", layout]
    if project.get("normalize"):
        flags.append("--normalize")
    # The watermark and the title card name the connected YouTube channel; with none known they stay blank.
    channel = publisher.channel() if publisher else {}
    if not isinstance(channel, dict):
        channel = {}
    if project.get("watermark", True) and channel.get("handle"):
        flags += ["--watermark", channel["handle"]]
    if channel.get("handle"):
        flags += ["--handle", channel["handle"]]
    if channel.get("name"):
        flags += ["--name", channel["name"]]
    if project.get("blurBg"):
        flags.append("--blur-bg")
    fade = float(project.get("fade") or 0)
    if not 0 <= fade <= 1:
        raise ValueError("fade must be between 0 and 1 second")
    if fade:
        flags += ["--fade", f"{fade:g}"]
    return flags


def track_line(c, i):
    """The @track line for a clip that follows a face, or "" when tracking is off or has nothing to follow."""
    keys = c.get("track")
    if not c.get("tracking") or not keys:
        return ""
    try:
        rel = [{"t": max(0.0, float(t) - float(c["in"])), "x": float(zx), "y": float(zy)} for t, zx, zy in keys]
        text = tracking.format_track(tracking.parse_track(tracking.format_track([(k["t"], k["x"], k["y"]) for k in tracking.simplify(rel)])))
    except (TypeError, ValueError, KeyError) as err:
        raise ValueError(f"clip {i} has a bad tracking path: {err}") from None
    return f"@track {text}"


def rendered_clips(project):
    """The clips that reach the Short: with the full template the bottom lane is kept in the project but not rendered."""
    count = LANE_COUNT.get(project.get("template") or "full", 1)
    return [c for c in project.get("clips", []) if LANES.index(c.get("lane") or "top") < count]


def lane_muted(project, clip):
    """Whether the project mutes the lane this clip sits in."""
    muted = project.get("laneMute")
    return isinstance(muted, dict) and bool(muted.get(clip.get("lane") or "top"))


def export_cuts(name, project, directory=None):
    lines = [f"# {project.get('hook') or name}"]
    clips = rendered_clips(project)
    if (project.get("template") or "full") != "full" and not any((c.get("lane") or "top") == "top" for c in clips):
        raise ValueError("This layout needs at least one clip in the top lane")
    carry = ""
    for i, c in enumerate(clips, 1):
        carried = False
        note = str(c.get("note", "")).replace("\n", " ").strip()
        if note:
            lines.append(f"# {i}. {note}")
        caption = " ".join(str(c.get("caption", "")).split())
        if (c.get("lane") or "top") == "top":
            # A plain caption carries on over the top-lane clips after it that have none, until one stops it.
            if caption:
                carry = caption if (c.get("capMode") or "text") == "text" or not c.get("words") else ""
            elif c.get("capStop"):
                carry = ""
            elif carry:
                caption, carried = carry, True
        if caption:
            lines.append(f"@caption {caption}")
        mode = c.get("capMode") or "text"
        if mode not in CAPMODES:
            raise ValueError(f"clip {i} has an unknown caption style")
        words = c.get("words") or []
        if mode != "text" and words:
            if not isinstance(words, list) or len(words) > MAX_WORDS:
                raise ValueError(f"clip {i} has too many spoken words")
            lines.append(f"@capmode {mode}")
            try:
                packed = [[str(w[0]), float(w[1]), float(w[2])] for w in words]
            except (TypeError, ValueError, IndexError):
                raise ValueError(f"clip {i} has a spoken word without a time")
            # Times are from the in point they were heard at; a later trim moves the speech by the difference. Words
            # before the new in point are kept in the project but not rendered.
            try:
                shift = float(c.get("wordsIn", c.get("in", 0))) - float(c.get("in", 0))
            except (TypeError, ValueError):
                raise ValueError(f"clip {i} has a bad timing start")
            packed = [[t, round(max(a + shift, 0.0), 3), round(b + shift, 3)] for t, a, b in packed if b + shift > 0]
            if packed:
                lines.append("@words " + json.dumps(packed, separators=(",", ":")))
            else:
                lines.pop()
        for key, low, high in (("speed", 0.25, 4.0), ("volume", 0.0, 3.0)):
            value = float(c.get(key, 1.0))
            if key == "volume" and lane_muted(project, c):
                value = 0.0
            if not low <= value <= high:
                raise ValueError(f"clip {i} has a {key} outside {low:g} to {high:g}")
            if value != 1.0:
                lines.append(f"@{key} {value:g}")
        ramp, freeze = c.get("ramp") or "none", float(c.get("freeze") or 0)
        if ramp not in RAMPS:
            raise ValueError(f"clip {i} has an unknown speed ramp")
        if not 0 <= freeze <= 3:
            raise ValueError(f"clip {i} has a hold outside 0 to 3 seconds")
        if ramp != "none":
            lines.append(f"@ramp {ramp}")
        if freeze:
            lines.append(f"@freeze {freeze:g}")
        for key, default in GRADE_DEFAULTS.items():
            value = float(c.get(key, default))
            low, high = GRADE_RANGES[key]
            if not low <= value <= high:
                raise ValueError(f"clip {i} has invalid {key}")
            if value != default:
                lines.append(f"@{key} {value:g}")
        effect = c.get("effect", "none")
        if effect not in EFFECT_NAMES:
            raise ValueError(f"clip {i} has an unknown effect")
        if effect != "none":
            lines.append(f"@effect {effect}")
        zoom = float(c.get("zoom", 1.0))
        if not 0.25 <= zoom <= 4.0:
            raise ValueError(f"clip {i} has a zoom outside 0.25 to 4")
        if zoom != 1.0:
            lines.append(f"@zoom {zoom:g}")
            for key in ("zx", "zy"):
                at = float(c.get(key, 0.5))
                if not 0.0 <= at <= 1.0:
                    raise ValueError(f"clip {i} has a zoom position outside 0 to 1")
                if at != 0.5:
                    lines.append(f"@{key} {at:g}")
            track = track_line(c, i)
            if track:
                lines.append(track)
        for key, tag in (("fadeIn", "fadein"), ("fadeOut", "fadeout")):
            seconds = float(c.get(key) or 0)
            if not 0.0 <= seconds <= 3.0:
                raise ValueError(f"clip {i} has a fade outside 0 to 3 seconds")
            if seconds:
                lines.append(f"@{tag} {seconds:g}")
        transition = c.get("transition") or "none"
        if transition not in TRANSITIONS:
            raise ValueError(f"clip {i} has an unknown transition")
        if transition != "none":
            seconds = float(c.get("tlen") or 0.3)
            if not 0.1 <= seconds <= 1.5:
                raise ValueError(f"clip {i} has a transition outside 0.1 to 1.5 seconds")
            lines.append(f"@transition {transition}")
            lines.append(f"@tlen {seconds:g}")
        style = {} if carried else c
        if style.get("capX") is not None and style.get("capY") is not None:
            for key, tag in (("capX", "capx"), ("capY", "capy")):
                at = float(style[key])
                if not 0.0 <= at <= 1.0:
                    raise ValueError(f"clip {i} has a caption position outside 0 to 1")
                lines.append(f"@{tag} {at:.4f}".rstrip("0").rstrip("."))
        if style.get("capLook"):
            if style["capLook"] not in LOOKS:
                raise ValueError(f"clip {i} has an unknown caption look")
            lines.append(f"@caplook {c['capLook']}")
        if style.get("capHi"):
            if not HEX_COLOUR.match(str(c["capHi"])):
                raise ValueError(f"clip {i} has a caption highlight that is not a colour")
            lines.append(f"@caphi {c['capHi']}")
        for key, tag, low, high in (("capScale", "capscale", 0.3, 3.0), ("capRot", "caprot", -180.0, 180.0)):
            if style.get(key) is not None:
                value = float(style[key])
                if not low <= value <= high:
                    raise ValueError(f"clip {i} has a caption {tag[3:]} outside {low:g} to {high:g}")
                lines.append(f"@{tag} {value:g}")
        lane = c.get("lane") or "top"
        if lane not in LANES:
            raise ValueError(f"clip {i} is in an unknown lane")
        if lane != "top":
            lines.append(f"@lane {lane}")
        fit = c.get("fit", "fit")
        if fit not in ("fit", "fill"):
            raise ValueError(f"clip {i} has an unknown fit")
        if fit == "fill":
            pan = float(c.get("pan", 0.5))
            if not 0.0 <= pan <= 1.0:
                raise ValueError(f"clip {i} has a pan outside 0 to 1")
            lines.append("@fit fill")
            if pan != 0.5:
                lines.append(f"@pan {pan:g}")
        src, start, end = str(c["src"]), float(c["in"]), float(c["out"])
        if "\n" in src or " | " in src or not 0 <= start < end:
            raise ValueError(f"clip {i} has a bad source or range")
        if c.get("voice"):
            if not Path(src).is_file():
                raise ValueError(f"clip {i} is a saved file, so its voice can't be isolated")
            voice = voice_isolation.cached_path(VOICE_DIR, src, *rounded_range(start, end))
            if not voice.is_file():
                if voice_isolation.working(VOICE_DIR, src, *rounded_range(start, end)):
                    raise ValueError(f"Clip {i}'s voice is still being isolated. Try again in a moment")
                raise ValueError(f"Clip {i} needs its voice isolated again, its range changed")
            lines.append(f"@voice {voice}")
        if not Path(src).is_file():
            saved = indexed_cut(src, start, end)
            if not saved:
                raise ValueError(f"clip {i}'s video was removed and the clip was never saved as a file")
            meta = probe(cut_path(saved))
            src, start, end = str(cut_path(saved)), 0.0, min(end - start, meta["duration"] if meta else end - start)
        lines.append(f"{src} | {fmt_time(start)} - {fmt_time(end)}")
    text = "\n".join(lines) + "\n"
    target = directory or PROJECT_DIR
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{name}.cuts.txt").write_text(text)
    hook = shlex.quote(project.get("hook") or "")
    extra = "".join(f" {flag}" for flag in render_flags(project))
    video = short_folder(name) / "video.mp4"
    shown = video.relative_to(ROOT) if video.is_relative_to(ROOT) else video
    command = (f"python3 scripts/make_short.py --cuts projects/{name}.cuts.txt --card{extra} "
               f"--text {hook} -o {shlex.quote(str(shown))}")
    return text, command


class Handler(BaseHTTPRequestHandler):
    server_version = "ClipBench"

    def handle_one_request(self):
        self.started = time.monotonic()
        super().handle_one_request()

    def log_message(self, fmt, *args):
        pass

    def log_request(self, code="-", size="-"):
        status = int(code) if str(code).isdigit() else 0
        level = logbook.request_level(self.command or "", self.path or "", status)
        if level is None:
            return
        started = getattr(self, "started", None)
        taken = f" {round((time.monotonic() - started) * 1000)}ms" if started else ""
        http_log.log(level, "%s %s %s%s", self.command, self.path, code, taken)

    def host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def origin_ok(self):
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        port = self.server.server_address[1]
        return origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    def send_html(self, text, status=200):
        page = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                "<title>Clipbench</title><style>body{margin:0;min-height:100vh;display:grid;place-content:center;"
                "gap:8px;background:#141414;color:#ececec;font:15px/1.5 Inter,system-ui,sans-serif;text-align:center;padding:24px}"
                "h3{margin:0;font-size:20px;font-weight:600}p{margin:0;color:#8c8c8c}</style>" + text)
        body = page.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def receive_video(self, name, audio=False, broll=False, project=None):
        length = int(self.headers.get("Content-Length") or 0)
        target = upload_target(name, AUDIO_EXTS, AUDIO_DIR) if audio else upload_target(name, None, BROLL_DIR if broll else None)
        if target is None:
            kinds = "an audio file (mp3, wav, m4a, aac, ogg, flac, aiff)" if audio else "a video file (mp4, mov, m4v, mkv, webm, avi)"
            return self.send_json({"error": f"That isn't {kinds}"}, 400)
        if not 0 < length <= MAX_UPLOAD:
            return self.send_json({"error": "The file is empty or over 8 GB"}, 400)
        part = target.with_name(f".{target.name}.part")
        try:
            with open(part, "wb") as out:
                left = length
                while left:
                    chunk = self.rfile.read(min(UPLOAD_CHUNK, left))
                    if not chunk:
                        raise OSError("the upload stopped early")
                    out.write(chunk)
                    left -= len(chunk)
            part.rename(target)
        except OSError as err:
            part.unlink(missing_ok=True)
            return self.send_json({"error": f"Couldn't save the file: {err}"}, 500)
        if project and not audio:
            store.claim_video(target, project)
        if not audio and not broll:
            prepare_after_download(target)
        return self.send_json({"ok": True, "path": str(target)})

    def import_sound(self, body):
        file_name = str(body.get("file", ""))
        try:
            data = soundbank.fetch(file_name)
        except ValueError as err:
            return self.send_json({"error": str(err)}, 400)
        except OSError as err:
            return self.send_json({"error": f"Couldn't get that sound: {err}"}, 502)
        target = upload_target(f"{body.get('name') or 'Sound'}{audio_suffix(data[:12])}", AUDIO_EXTS, AUDIO_DIR)
        try:
            target.write_bytes(data)
        except OSError as err:
            target.unlink(missing_ok=True)
            return self.send_json({"error": f"Couldn't save that sound: {err}"}, 500)
        return self.send_json({"ok": True, "path": str(target)})

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return None

    def serve_file(self, path, ctype):
        stamp = path.stat()
        size = stamp.st_size
        etag = f'"{stamp.st_mtime_ns:x}-{size:x}-{stamp.st_ctime_ns:x}"'
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        if rng and self.headers.get("If-Range") and self.headers.get("If-Range") != etag:
            rng = None
        validators = [tag.strip().removeprefix("W/") for tag in self.headers.get("If-None-Match", "").split(",")]
        if not rng and (etag in validators or "*" in validators):
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "private, no-cache")
            self.end_headers()
            return
        status = 200
        if rng and (m := re.match(r"bytes=(\d*)-(\d*)", rng)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            elif m.group(2):
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            if start > end:
                self.send_error(416)
                return
            status = 206
        self.send_response(status)
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "private, no-cache")
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if not self.host_ok():
            return self.send_error(403)
        path = unquote(urlparse(self.path).path)
        if path == "/avatar.png" and AVATAR_FILE.is_file():
            return self.serve_file(AVATAR_FILE, "image/png")
        static = {"/": ("home.html", "text/html; charset=utf-8"),
                  "/editor": ("index.html", "text/html; charset=utf-8"),
                  "/home.css": ("home.css", "text/css"),
                  "/home.js": ("home.js", "text/javascript"),
                  "/home-projects.js": ("home-projects.js", "text/javascript"),
                  "/planet.js": ("planet.js", "text/javascript"),
                  "/assets/mars-texture.jpg": ("assets/mars-texture.jpg", "image/jpeg"),
                  "/assets/mars.jpg": ("assets/mars.jpg", "image/jpeg"),
                  "/assets/planet-logo.svg": ("assets/planet-logo.svg", "image/svg+xml"),
                  "/favicon.ico": ("assets/planet-logo.svg", "image/svg+xml"),
                  "/style.css": ("style.css", "text/css"),
                  "/app.js": ("app.js", "text/javascript"),
                  "/youtube.js": ("youtube.js", "text/javascript"),
                  "/shorts.js": ("shorts.js", "text/javascript"),
                  "/dropzone.js": ("dropzone.js", "text/javascript"),
                  "/short.js": ("short.js", "text/javascript"),
                  "/timeline.js": ("timeline.js", "text/javascript"),
                  "/selection.js": ("selection.js", "text/javascript"),
                  "/framer.js": ("framer.js", "text/javascript"),
    "/seams.js": ("seams.js", "text/javascript"),
    "/reframe.js": ("reframe.js", "text/javascript"),
    "/tighten.js": ("tighten.js", "text/javascript"),
    "/review.js": ("review.js", "text/javascript"),
    "/autolayout.js": ("autolayout.js", "text/javascript"),
    "/drafts.js": ("drafts.js", "text/javascript"),
    "/reframebox.js": ("reframebox.js", "text/javascript"),
    "/lanes.js": ("lanes.js", "text/javascript"),
    "/shuttle.js": ("shuttle.js", "text/javascript"),
    "/tlresize.js": ("tlresize.js", "text/javascript"),
    "/textpanel.js": ("textpanel.js", "text/javascript"),
    "/clipresize.js": ("clipresize.js", "text/javascript"),
                  "/zoom.js": ("zoom.js", "text/javascript"),
                  "/snap.js": ("snap.js", "text/javascript"),
                  "/suggest.js": ("suggest.js", "text/javascript"),
                  "/dialogue.js": ("dialogue.js", "text/javascript"),
                  "/audio.js": ("audio.js", "text/javascript"),
                  "/captions.js": ("captions.js", "text/javascript"),
                  "/livecap.js": ("livecap.js", "text/javascript"),
                  "/voice.js": ("voice.js", "text/javascript"),
                  "/vocals.js": ("vocals.js", "text/javascript"),
                  "/clippreview.js": ("clippreview.js", "text/javascript"),
                  "/live.js": ("live.js", "text/javascript"),
                  "/streamers.js": ("streamers.js", "text/javascript"),
                  "/shortcuts.js": ("shortcuts.js", "text/javascript"),
                  "/blend.js": ("blend.js", "text/javascript"),
                  "/rail.js": ("rail.js", "text/javascript"),
                  "/grade.js": ("grade.js", "text/javascript"),
                  "/panels.js": ("panels.js", "text/javascript"),
                  "/soundbank.js": ("soundbank.js", "text/javascript")}
        if path in static:
            name, ctype = static[path]
            return self.serve_file(UI_DIR / name, ctype)
        if path == "/api/library":
            try:
                return self.send_json(scan_library(project_arg(parse_qs(urlparse(self.path).query))))
            except ValueError as err:
                return self.send_json({"error": str(err)}, 400)
        if path == "/api/audio":
            return self.send_json(scan_audio())
        if path == "/api/soundbank":
            q = parse_qs(urlparse(self.path).query)
            try:
                return self.send_json(soundbank.browse(q.get("q", [""])[0][:80], int(q.get("page", ["1"])[0])))
            except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as err:
                return self.send_json({"error": f"Couldn't reach the sound library: {err}"}, 502)
        if m := re.fullmatch(r"/api/audio-wave/([0-9a-f]{12})", path):
            wave = load_audio_wave(m.group(1))
            return self.send_json(wave) if wave is not None else self.send_json({}, 404)
        if m := re.fullmatch(r"/audio-file/([0-9a-f]{12})", path):
            sound = audio_registry.get(m.group(1))
            if sound is None or not sound.is_file():
                scan_audio()
                sound = audio_registry.get(m.group(1))
            return self.serve_file(sound, audio_type(sound)) if sound and sound.is_file() else self.send_error(404)
        if path == "/api/streamers":
            return self.send_json(streamers.load(STREAMER_FILE))
        if path == "/api/favorites":
            try:
                return self.send_json(store.list_favorites(project_arg(parse_qs(urlparse(self.path).query))))
            except ValueError as err:
                return self.send_json({"error": str(err)}, 400)
        if path == "/api/projects":
            return self.send_json(store.list_projects())
        if m := re.fullmatch(r"/api/project/([A-Za-z0-9_-]+)", path):
            project = store.get_project(m.group(1))
            return self.send_json(project) if project is not None else self.send_json({}, 404)
        if m := re.fullmatch(r"/api/rendered-project/([A-Za-z0-9_-]+)", path):
            snap = rendered_project(m.group(1))
            return self.send_json(snap) if snap is not None else self.send_json({}, 404)
        if path == "/api/home-recent":
            recent = store.recent_projects(None if parse_qs(urlparse(self.path).query).get("all") == ["1"] else 3)
            for item in recent:
                src = item.pop("src", None)
                vid = video_id(src) if src else None
                if not item["thumb"] and vid in registry:
                    item["thumb"] = f"/video-thumb/{vid}.jpg"
            return self.send_json(recent)
        if path == "/api/home-project":
            preferred = parse_qs(urlparse(self.path).query).get("name", [None])[0]
            return self.send_json(store.home_project(preferred))
        if path == "/api/youtube":
            return self.send_json({**publisher.status(), "best_time": best_time_text(video_stats.best_day())})
        if path == "/api/uploads/progress":
            names = list(dict.fromkeys(parse_qs(urlparse(self.path).query).get("name", [])))
            if any(not PROJECT_NAME.fullmatch(name) for name in names):
                return self.send_json({"error": "That isn't a project name"}, 400)
            return self.send_json({name: publisher.state(name) for name in names})
        if path == "/api/shorts":
            video_stats.refresh_soon()
            return self.send_json(with_stats(list_shorts(SHORT_DIR, store.list_projects(), publisher.state, short_duration), store.video_stats()))
        if path == "/api/video-stats":
            return self.send_json(video_stats.status())
        if m := re.fullmatch(r"/clip-thumb/([0-9a-f]{64})\.(jpg|png|webp)", path):
            thumb = CLIP_THUMB_DIR / f"{m.group(1)}.{m.group(2)}"
            return self.serve_file(thumb, "image/" + ("jpeg" if m.group(2) == "jpg" else m.group(2))) if thumb.is_file() else self.send_error(404)
        if m := re.fullmatch(r"/video-thumb/([0-9a-f]{12})\.jpg", path):
            thumb = video_thumb(m.group(1))
            return self.serve_file(thumb, "image/jpeg") if thumb else self.send_error(404)
        if m := re.fullmatch(r"/short-thumb/([A-Za-z0-9_-]+)\.jpg", path):
            thumb = thumbnail(short_folder(m.group(1)))
            return self.serve_file(thumb, "image/jpeg") if thumb else self.send_error(404)
        if path == CALLBACK_PATH:
            try:
                publisher.finish_connect(self.server.server_address[1], parse_qs(urlparse(self.path).query))
            except yt.YouTubeError as err:
                return self.send_html(f"<h3>Not connected</h3><p>{html.escape(str(err))}</p>", 400)
            return self.send_html("<h3>YouTube connected</h3><p>You can close this tab and go back to the clip bench.</p>")
        if m := re.fullmatch(r"/api/upload/([A-Za-z0-9_-]+)", path):
            video = short_folder(m.group(1)) / "video.mp4"
            state = publisher.state(m.group(1))
            return self.send_json(current_upload(state, video.stat().st_mtime) if video.is_file() else state)
        if m := re.fullmatch(r"/api/proxy/([0-9a-f]{12})", path):
            return self.send_json(proxy_status(m.group(1), wait=parse_qs(urlparse(self.path).query).get("wait") == ["1"]))
        if m := re.fullmatch(r"/api/download/([0-9a-f]{12})", path):
            return self.send_json(downloads.get(m.group(1)) or {"state": "error", "message": "unknown download"}, 200)
        if m := re.fullmatch(r"/api/wave/([0-9a-f]{12})", path):
            wave = load_wave(m.group(1))
            return self.send_json(wave) if wave is not None else self.send_json({}, 404)
        if m := re.fullmatch(r"/api/scenes/([0-9a-f]{12})", path):
            return self.send_json(get_scenes(m.group(1)))
        if m := re.fullmatch(r"/api/index-speech/([0-9a-f]{12})", path):
            return self.send_json(index_jobs.get(m.group(1)) or {"state": "none"})
        if path == "/api/dialogue":
            query = parse_qs(urlparse(self.path).query)
            try:
                return self.send_json(search_dialogue(query.get("q", [""])[0][:120], project_arg(query)))
            except ValueError as err:
                return self.send_json({"error": str(err)}, 400)
        if m := re.fullmatch(r"/api/suggest/([0-9a-f]{12})", path):
            return self.send_json(get_suggest(m.group(1)))
        if m := re.fullmatch(r"/api/review/([0-9a-f]{12})", path):
            if m.group(1) not in registry:
                return self.send_json({"error": "unknown video"}, 400)
            return self.send_json({"reviews": [{"in": r["in"], "out": r["out"], "decision": r["decision"]} for r in store.suggestion_reviews(m.group(1))]})
        if m := re.fullmatch(r"/api/prepare/([0-9a-f]{12})", path):
            return self.send_json(prepare_queue.get(m.group(1)))
        if m := re.fullmatch(r"/api/follow/([0-9a-f]{12})", path):
            return self.send_json(dict(follow_jobs.get(m.group(1)) or {"state": "error", "message": "unknown job"}))
        if m := re.fullmatch(r"/api/render/([A-Za-z0-9_-]+)", path):
            return self.send_json(renders.get(m.group(1)) or {"state": "none"})
        if m := re.fullmatch(r"/api/instrumental/([0-9a-f]{12})", path):
            return self.send_json(instrumental_jobs.get(m.group(1)) or {"state": "error", "message": "unknown job"})
        if m := re.fullmatch(r"/api/voice/([0-9a-f]{12})", path):
            return self.send_json(voice_jobs.get(m.group(1)) or {"state": "error", "message": "unknown job"})
        if m := re.fullmatch(r"/api/transcribe/([0-9a-f]{12})", path):
            return self.send_json(transcripts.get(m.group(1)) or {"state": "error", "message": "unknown job"})
        if m := re.fullmatch(r"/api/publish/([A-Za-z0-9_-]+)", path):
            return self.send_json(read_publish(m.group(1)))
        if m := re.fullmatch(r"/api/preview/([A-Za-z0-9_-]+)", path):
            return self.send_json(renders.get(preview_key(m.group(1))) or {"state": "none"})
        if m := re.fullmatch(r"/preview/([A-Za-z0-9_-]+)\.mp4", path):
            if not preview_path(m.group(1)).is_file():
                return self.send_error(404)
            return self.serve_file(preview_path(m.group(1)), "video/mp4")
        if m := re.fullmatch(r"/short/([A-Za-z0-9_-]+)\.mp4", path):
            video = short_folder(m.group(1)) / "video.mp4"
            if not video.is_file():
                return self.send_error(404)
            return self.serve_file(video, "video/mp4")
        if path == "/api/cuts/progress":
            return self.send_json(warm_progress())
        if m := re.fullmatch(r"/api/cut/([0-9a-f]{16})", path):
            return self.send_json(cut_status(m.group(1)))
        if m := re.fullmatch(r"/cut/([0-9a-f]{16})\.mp4", path):
            if not cut_path(m.group(1)).is_file():
                return self.send_error(404)
            return self.serve_file(cut_path(m.group(1)), "video/mp4")
        if m := re.fullmatch(r"/voice/([0-9a-f]{16})\.wav", path):
            voice = VOICE_DIR / f"{m.group(1)}.wav"
            if not voice.is_file():
                return self.send_error(404)
            return self.serve_file(voice, "audio/wav")
        if m := re.fullmatch(r"/media/([0-9a-f]{12})", path):
            src = registry.get(m.group(1))
            if not src:
                return self.send_error(404)
            if proxy_path(m.group(1)).is_file():
                return self.serve_file(proxy_path(m.group(1)), "video/mp4")
            if not src.is_file():
                return self.send_error(404)
            meta = probe(src)
            if meta and plays_directly(src, meta):
                return self.serve_file(src, "video/mp4")
            return self.send_error(409, "needs proxy")
        self.send_error(404)

    def do_POST(self):
        if not self.host_ok() or not self.origin_ok():
            return self.send_error(403)
        path = urlparse(self.path).path
        if m := re.fullmatch(r"/api/proxy/([0-9a-f]{12})", path):
            return self.send_json(start_proxy(m.group(1)))
        if m := re.fullmatch(r"/api/suggest/([0-9a-f]{12})", path):
            return self.send_json(start_suggest(m.group(1)))
        if m := re.fullmatch(r"/api/remove-video/([0-9a-f]{12})", path):
            try:
                return self.send_json({"ok": True, "how": remove_video(m.group(1))})
            except (ValueError, OSError) as err:
                return self.send_json({"error": str(err)}, 400)
        if path == "/api/cuts/warm":
            threading.Thread(target=warm_cuts, daemon=True).start()
            return self.send_json({"ok": True})
        if path == "/api/cut":
            body = self.read_json() or {}
            try:
                return self.send_json(start_cut(str(body.get("src", "")), float(body["in"]), float(body["out"])))
            except (ValueError, KeyError, TypeError, OSError) as err:
                return self.send_json({"error": str(err)}, 400)
        if path == "/api/upload-video":
            query = parse_qs(urlparse(self.path).query)
            try:
                project = project_arg(query)
            except ValueError as err:
                return self.send_json({"error": str(err)}, 400)
            return self.receive_video(query.get("name", [""])[0], broll=query.get("broll", [""])[0] == "1", project=project)
        if path == "/api/upload-audio":
            return self.receive_video(parse_qs(urlparse(self.path).query).get("name", [""])[0], audio=True)
        body = self.read_json()
        if body is None:
            return self.send_json({"error": "bad json"}, 400)
        if path == "/api/soundbank/import":
            return self.import_sound(body)
        if path == "/api/add":
            p = Path(str(body.get("path", "")).strip().strip("'\"")).expanduser()
            if not p.is_file() or p.suffix.lower() not in VIDEO_EXTS:
                return self.send_json({"error": "not a video file"}, 400)
            project = str(body.get("project") or "")
            if project and not PROJECT_NAME.fullmatch(project):
                return self.send_json({"error": "That isn't a project name"}, 400)
            store.add_extra_video(p)
            if project:
                store.claim_video(p, project)
            prepare_after_download(p)
            return self.send_json({"ok": True})
        if path == "/api/project-copy":
            source, target = str(body.get("from", "")), str(body.get("to", ""))
            if not (PROJECT_NAME.fullmatch(source) and PROJECT_NAME.fullmatch(target)):
                return self.send_json({"error": "That isn't a project name"}, 400)
            store.copy_assets(source, target)
            return self.send_json({"ok": True})
        if path == "/api/project-create":
            name = str(body.get("name", "")).strip()
            if not PROJECT_NAME.fullmatch(name):
                return self.send_json({"error": "Use letters, numbers, dashes or underscores (up to 60 characters)."}, 400)
            project = {"name": name, "clips": [], "bank": [], "audio": [], "format": "9:16", "template": "full", "layout": "title", "watermark": True}
            if not store.create_project(name, project):
                return self.send_json({"error": "A project with this name already exists."}, 409)
            store.mark_own_media(name)
            return self.send_json({"name": name})
        if path == "/api/project-delete":
            name = str(body.get("name", ""))
            if not PROJECT_NAME.fullmatch(name):
                return self.send_json({"error": "That isn't a project name"}, 400)
            store.delete_project(name)
            return self.send_json({"ok": True})
        if path == "/api/instrumental":
            scan_audio()
            src = audio_registry.get(str(body.get("id", "")))
            if not src:
                return self.send_json({"error": "unknown song"}, 400)
            if not voice_isolation.available() and not instrumental.target_for(src).is_file():
                return self.send_json({"id": "none", "state": "error", "message": voice_isolation.HINT})
            return self.send_json(start_instrumental(src))
        if path == "/api/voice":
            src = str(body.get("src", ""))
            try:
                start, end = float(body["in"]), float(body["out"])
            except (KeyError, TypeError, ValueError):
                return self.send_json({"error": "bad range"}, 400)
            if src not in {str(p) for p in registry.values()}:
                return self.send_json({"error": "unknown video"}, 400)
            if not 0 <= start < end or end - start > MAX_TRANSCRIBE:
                return self.send_json({"error": f"Pick a clip under {MAX_TRANSCRIBE:g} seconds"}, 400)
            if not voice_isolation.available() and not voice_isolation.cached_path(VOICE_DIR, src, *rounded_range(start, end)).is_file():
                return self.send_json({"id": "none", "state": "error", "message": voice_isolation.HINT})
            return self.send_json(start_voice(src, start, end))
        if path == "/api/index-speech":
            return self.send_json(start_index(str(body.get("id", ""))))
        if path == "/api/transcribe":
            src = str(body.get("src", ""))
            try:
                start, end = float(body["in"]), float(body["out"])
            except (KeyError, TypeError, ValueError):
                return self.send_json({"error": "bad range"}, 400)
            known = {str(p) for p in registry.values()}
            if src not in known:
                return self.send_json({"error": "unknown video"}, 400)
            if not 0 <= start < end or end - start > MAX_TRANSCRIBE:
                return self.send_json({"error": f"Pick a clip under {MAX_TRANSCRIBE:g} seconds"}, 400)
            task = "transcribe" if body.get("task") == "transcribe" else "translate"
            if body.get("subtitles") and not embedded_subs.has_subtitles(src):
                return self.send_json({"id": "none", "state": "none"})
            known_words = speech_cache().find(src, start, end) if body.get("timed") and task == "translate" else None
            if known_words:
                return self.send_json({"id": "cached", "state": "done", "text": " ".join(w[0] for w in known_words), "words": known_words})
            return self.send_json(start_transcribe(src, start, end, bool(body.get("timed")), task))
        if path == "/api/reframe":
            src = str(body.get("src", ""))
            try:
                start, end = float(body["in"]), float(body["out"])
            except (KeyError, TypeError, ValueError):
                return self.send_json({"error": "bad range"}, 400)
            if src not in {str(p) for p in registry.values()}:
                return self.send_json({"error": "unknown video"}, 400)
            try:
                return self.send_json(reframe_analysis(src, start, end))
            except reframe.NoFaceDetector as err:
                return self.send_json({"error": str(err)}, 400)
            except ImportError:
                return self.send_json({"error": "AI reframe needs OpenCV: pip install opencv-python-headless"}, 400)
            except (ValueError, OSError, subprocess.SubprocessError) as err:
                return self.send_json({"error": str(err)[:300]}, 400)
        if path == "/api/speaker":
            src = str(body.get("src", ""))
            try:
                start, end = float(body["in"]), float(body["out"])
            except (KeyError, TypeError, ValueError):
                return self.send_json({"error": "bad range"}, 400)
            if src not in {str(p) for p in registry.values()}:
                return self.send_json({"error": "unknown video"}, 400)
            try:
                return self.send_json(speaker_analysis(src, start, end))
            except ImportError:
                return self.send_json({"error": "Follow the speaker needs OpenCV: pip install opencv-python-headless"}, 400)
            except (ValueError, OSError, subprocess.SubprocessError) as err:
                return self.send_json({"error": str(err)[:300]}, 400)
        if path == "/api/layout":
            src = str(body.get("src", ""))
            try:
                start, end = float(body["in"]), float(body["out"])
            except (KeyError, TypeError, ValueError):
                return self.send_json({"error": "bad range"}, 400)
            if src not in {str(p) for p in registry.values()}:
                return self.send_json({"error": "unknown video"}, 400)
            try:
                return self.send_json(layout_analysis(src, start, end))
            except ImportError:
                return self.send_json({"error": "Auto layout needs OpenCV: pip install opencv-python-headless"}, 400)
            except (ValueError, OSError, subprocess.SubprocessError) as err:
                return self.send_json({"error": str(err)[:300]}, 400)
        if m := re.fullmatch(r"/api/review/([0-9a-f]{12})", path):
            try:
                return self.send_json(review_suggestion(m.group(1), body))
            except ValueError as err:
                return self.send_json({"error": str(err)}, 400)
        if path == "/api/pauses":
            src = str(body.get("src", ""))
            try:
                start, end = float(body["in"]), float(body["out"])
            except (KeyError, TypeError, ValueError):
                return self.send_json({"error": "bad range"}, 400)
            if src not in {str(p) for p in registry.values()}:
                return self.send_json({"error": "unknown video"}, 400)
            if not 0 <= start < end:
                return self.send_json({"error": "bad range"}, 400)
            try:
                return self.send_json(pauses.pauses(src, start, end))
            except (OSError, subprocess.SubprocessError, ValueError) as err:
                return self.send_json({"error": str(err)[:300]}, 400)
        if path == "/api/follow":
            src = str(body.get("src", ""))
            try:
                start, end = float(body["in"]), float(body["out"])
                box = {k: float(body["box"][k]) for k in ("x", "y", "w", "h")}
                at = float(body.get("at", start))
            except (KeyError, TypeError, ValueError):
                return self.send_json({"error": "bad range or box"}, 400)
            if src not in {str(p) for p in registry.values()}:
                return self.send_json({"error": "unknown video"}, 400)
            return self.send_json(start_follow(src, start, end, box, at))
        if path in ("/api/live-record", "/api/live-record/stop"):
            return self.send_json(*record_call(path, body))
        if path in ("/api/streamers", "/api/streamers/remove", "/api/streamers/live"):
            return self.send_json(*streamer_call(path, body))
        if path == "/api/live-buffer":
            url = str(body.get("url", "")).strip()
            if not valid_url(url):
                return self.send_json({"error": "Paste a full link that starts with http or https"}, 400)
            try:
                return self.send_json({"seconds": round(live_buffer(url))})
            except (ValueError, OSError, subprocess.SubprocessError) as err:
                return self.send_json({"error": str(err)[:300]}, 400)
        if path == "/api/download":
            url = str(body.get("url", "")).strip()
            if not valid_url(url):
                return self.send_json({"error": "Paste a full link that starts with http or https"}, 400)
            section, live_wall = None, None
            if body.get("live"):
                try:
                    live_wall = (float(body["wall_start"]), float(body["wall_end"]))
                except (KeyError, TypeError, ValueError):
                    return self.send_json({"error": "bad range"}, 400)
                if not live_wall[0] < live_wall[1] <= time.time() + 5 or live_wall[1] - live_wall[0] > MAX_SECTION:
                    return self.send_json({"error": f"Pick a stretch under {MAX_SECTION} seconds"}, 400)
            elif body.get("start") is not None or body.get("end") is not None:
                try:
                    start, end = float(body["start"]), float(body["end"])
                except (KeyError, TypeError, ValueError):
                    return self.send_json({"error": "bad range"}, 400)
                if not 0 <= start < end or end - start > MAX_SECTION:
                    return self.send_json({"error": f"Pick a stretch under {MAX_SECTION} seconds"}, 400)
                section = (start, end)
            project = str(body.get("project") or "")
            if project and not PROJECT_NAME.fullmatch(project):
                return self.send_json({"error": "That isn't a project name"}, 400)
            return self.send_json(start_download(url, section, live_wall, str(body.get("title", ""))[:200], project or None))
        if path == "/api/youtube/connect":
            try:
                return self.send_json({"url": publisher.begin_connect(self.server.server_address[1])})
            except yt.YouTubeError as err:
                return self.send_json({"error": str(err)}, 400)
        if path == "/api/youtube/disconnect":
            publisher.disconnect()
            return self.send_json({"ok": True})
        if m := re.fullmatch(r"/api/upload/([A-Za-z0-9_-]+)", path):
            info = read_publish(m.group(1))
            try:
                return self.send_json(publisher.start_upload(m.group(1), short_folder(m.group(1)) / "video.mp4",
                                                             info["title"], info["description"]))
            except yt.YouTubeAuthError as err:
                return self.send_json({"error": str(err), "reconnect": True}, 401)
            except yt.YouTubeError as err:
                return self.send_json({"error": str(err)}, 400)
        if m := re.fullmatch(r"/api/publish/([A-Za-z0-9_-]+)", path):
            try:
                write_publish(m.group(1), body)
            except ValueError as err:
                return self.send_json({"error": str(err)}, 400)
            return self.send_json({"ok": True})
        if m := re.fullmatch(r"/api/render/([A-Za-z0-9_-]+)", path):
            if not isinstance(body.get("clips"), list) or not body["clips"]:
                return self.send_json({"error": "Add at least one clip first"}, 400)
            try:
                return self.send_json(start_render(m.group(1), body))
            except (ValueError, KeyError, TypeError) as err:
                return self.send_json({"error": str(err)}, 400)
        if m := re.fullmatch(r"/api/preview/([A-Za-z0-9_-]+)", path):
            try:
                return self.send_json(start_preview(m.group(1), body.get("project") or {}, body.get("index")))
            except (ValueError, KeyError, TypeError) as err:
                return self.send_json({"error": str(err)}, 400)
        if m := re.fullmatch(r"/api/export/([A-Za-z0-9_-]+)", path):
            try:
                text, command = export_cuts(m.group(1), body)
            except (ValueError, KeyError, TypeError) as err:
                return self.send_json({"error": str(err)}, 400)
            return self.send_json({"cuts": text, "command": command, "file": f"workspace/projects/{m.group(1)}.cuts.txt"})
        self.send_error(404)

    def do_PUT(self):
        if not self.host_ok() or not self.origin_ok():
            return self.send_error(403)
        body = self.read_json()
        if urlparse(self.path).path == "/api/favorites":
            if not isinstance(body, list) or not all(isinstance(f, dict) and isinstance(f.get("src"), str) for f in body):
                return self.send_json({"error": "bad request"}, 400)
            if len(body) > FAVORITES_LIMIT:
                return self.send_json({"error": f"Saved holds up to {FAVORITES_LIMIT} clips. Remove some first"}, 400)
            try:
                project = project_arg(parse_qs(urlparse(self.path).query))
            except ValueError as err:
                return self.send_json({"error": str(err)}, 400)
            try:
                body, thumbs = ThumbnailStore(CLIP_THUMB_DIR).externalize(body)
            except OSError:
                thumbs = []  # Keep embedded thumbnails if image storage is unavailable.
            if project:
                store.replace_favorites_for(project, body)
            else:
                store.replace_favorites(body)
            return self.send_json({"ok": True, **({"thumbs": thumbs} if thumbs else {})})
        m = re.fullmatch(r"/api/project/([A-Za-z0-9_-]+)", urlparse(self.path).path)
        if not m or not isinstance(body, dict):
            return self.send_json({"error": "bad request"}, 400)
        try:
            body, thumbs = ThumbnailStore(CLIP_THUMB_DIR).externalize(body)
        except OSError:
            thumbs = []
        fresh = store.get_project(m.group(1)) is None
        store.put_project(m.group(1), body)
        if fresh:
            store.mark_own_media(m.group(1))
        store.claim_used_videos(body, m.group(1))
        self.send_json({"ok": True, **({"thumbs": thumbs} if thumbs else {})})


def main():
    ffmpeg_env.activate()
    sys.stderr = logbook.start(LOG_FILE, sys.stderr)
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()
    log.info("starting %s on port %s, python %s", ROOT, a.port, sys.version.split()[0])
    if not (UI_DIR / "index.html").is_file():
        sys.exit(f"missing UI: {UI_DIR / 'index.html'}")
    global store, publisher, video_stats
    store = Store(DB_FILE)
    imported = store.import_legacy(PROJECT_DIR)
    if imported:
        print(f"Moved {imported} project{'s' if imported != 1 else ''} into {DB_FILE} (the old files are untouched)")
    publisher = Publisher(store, CLIENT_FILE)
    video_stats = VideoStats(store, CLIENT_FILE)
    store.claim_used_videos()
    store.mark_existing_projects_own_media()
    prune_cuts()
    recorder.reap()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    atexit.register(recorder.stop)
    atexit.register(recorder.clear)
    threading.Thread(target=warm_cuts, daemon=True).start()
    try:
        server = LoggedServer(("127.0.0.1", a.port), Handler)
    except OSError as err:
        sys.exit(f"Can't start on port {a.port}: {err.strerror}. Is the clip bench already running? "
                 f"Stop it, or use --port to pick another.")
    url = f"http://127.0.0.1:{a.port}/"
    print(f"Clip bench on {url}  (Ctrl+C to stop)")
    print(f"Log file: {LOG_FILE}")
    if not a.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
