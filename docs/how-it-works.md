# How Clipbench works

Clipbench is a local tool for turning long videos into Shorts. One Python
process serves a browser UI and does the heavy lifting with FFmpeg, Whisper and
an optional local language model. Nothing leaves the machine except what you
choose to upload to YouTube.

This document is the map: what the pieces are, where things live, and how a
video becomes a published Short. The README covers installing and starting.

## The pieces

| Part | Where | What it does |
|---|---|---|
| Server | `scripts/clipper.py` | HTTP server on 127.0.0.1. Serves the UI, about seventy `/api/...` routes, media and proxies. Runs downloads, scans, listening, suggestions, renders and uploads in background threads. |
| UI | `scripts/clipper_ui/` | Plain HTML, CSS and JavaScript, no build step. `app.js` is the editor's core; every other file is one feature and says at its top which others it depends on. |
| Renderer | `scripts/make_short.py` | Command-line tool the server runs per render. Takes a cut list and flags, writes a 1080x1920 (or 1920x1080) video with captions, layout, effects and audio. |
| Store | `scripts/store.py` | SQLite. Projects, saved clips, which project owns which video, settings, upload history, channel videos and statistics, suggestion reviews. |
| Analysis | `clip_*.py`, `video_scan.py`, `suggest.py`, `learning.py` | Scene cuts, loudness, motion, speech, hooks and pauses turn into candidate moments with scores. |
| Speech | `fast_speech.py`, `mlx_speech.py`, `transcript_index.py`, `speech_cache.py` | Whisper on the GPU where available. Whole-video transcripts for search, per-clip words for captions. |
| Picture | `reframe.py`, `tracking.py`, `person_follow.py`, `speaker_follow.py`, `auto_layout.py`, `cam_memory.py` | Finding faces and people so a crop can follow them, and guessing a layout from who is in frame. |
| Sound | `voice_isolation.py`, `instrumental.py`, `clip_beat.py`, `soundbank.py`, `assemble_voice.py` | Demucs separation, beat detection, sound search and narration assembly. |
| Live | `live.js`, `liverec.py`, `streamers.py` | Watch a YouTube or Twitch stream in the editor, mark a stretch, and the server fetches just that stretch. |
| YouTube | `youtube.py`, `publisher.py`, `video_stats.py`, `shorts.py` | OAuth for a Desktop client, resumable upload, and hourly reads of views, likes, retention and the channel's own videos. |
| Tools | `tools/` | Setup helpers: pick a working Python, create the workspace, relocate an old install, fetch models, check the environment, export a starter pack. |

## Where things live

The root page serves `studio.html`, `studio.css`, and `studio.js`. Profiles and project
ownership live in SQLite; the browser remembers only the last selected profile. Schema
migration assigns existing projects to `default` without changing their saved edits.
`profile_accounts.py` creates a Publisher per profile. Its settings adapter namespaces
credentials and channel identity; Default retains the original keys for compatibility.
OAuth callbacks resolve their profile from the pending state, and uploads and render
watermarks resolve the account from the project's stored owner rather than browser state.
Source files and their existing project ownership rules remain in the same workspace.

Code sits in the repository. Everything the app downloads, makes or remembers
sits under `workspace/`, which git ignores as a whole.

```
workspace/
  clips/         source videos; .proxy/ holds per-video caches, .cuts/ cut clips
  temp/, broll/  more places the library lists videos from
  audio/, music/ songs and sound effects for the audio lane
  projects/      exported cut lists, one per project
  shorts/        rendered Shorts, NNN_name/video.mp4 with title and thumbnail
  channel/       avatar.png, drawn on the title card
  logs/          clipbench.log, everything the server printed, with timestamps
  data/          clipbench.db and everything keyed to it:
                 transcripts/, speech/, voice/, preview/, rendered/, clip-thumbs/, live/
                 youtube_client.json (your OAuth client), streamers.json
```

`CLIPBENCH_WORKSPACE` moves the whole workspace; `CLIPBENCH_DATA` moves only
`data/`, which is how tests and a second server run against their own database.

A video is known by a short hash of its place inside the workspace, for
example `clips/episode.mp4`. Its thumbnail, waveform, scene cuts, motion,
suggestions, proxy and transcript are all filed under that id, so the workspace
can move or the repository can be cloned somewhere else without those caches
being lost. Files outside the workspace are hashed by their full path.

## From a video to a Short

1. **Get the video in.** Paste a link and the server downloads it with yt-dlp
   into `workspace/clips/`, or drop a file onto the Media list, or clip a
   stretch straight out of a live stream. Each video is owned by the project
   that brought it in; other projects see it only when nobody has claimed it.

2. **Prepare it.** `prepare.py` runs in the background as soon as a video lands:
   one decode gives the scene cuts and the picture motion (`video_scan.py`), the
   audio becomes a waveform, and the video is listened to once for a
   transcript if it has no English subtitles. A browser-friendly proxy is made
   only if the original will not play directly. Proxy conversions run one at a time
   in a FIFO queue, so switching between incompatible sources does not launch
   competing encoders. Failed jobs report an error and leave the worker free
   to prepare the next video.

3. **Find the moments.** `suggest.py` builds candidate windows that start and
   end on finished sentences or scene cuts, scores each from the opening
   (`clip_hook.py`), loudness, wording, motion and length, weighted by what kind
   of video it is (`clip_profile.py`: talk, quiet, fast-cut or mixed). The forty
   strongest distinct stretches go to the local model one at a time, which
   labels each (joke, shock, emotion, cliffhanger, reveal, action, explanation)
   and marks it. The list fills in on screen as answers arrive, best first.
   Nearby short moments are also offered joined as one Short with the gap cut.

4. **Learn.** Keep and Skip on a suggestion, and the retention curve of every
   Short already on the channel, become lessons (`learning.py`): what a label,
   a label in that kind of video, a strong or weak hook, sound or wording did
   before. Future suggestions are nudged by them, and each row says why.

5. **Cut.** In the Clips station you mark in and out points on the video, save
   clips to the project, search dialogue across every video, and cut talk
   tighter by removing pauses. Each clip carries its own words from Whisper for
   captions.

6. **Lay it out.** The Short station is a lane timeline over a phone-shaped
   preview. Layouts put one clip full frame, two stacked, side by side or a
   grid; crops can follow a face or a person; captions, speed, volume, effects,
   transitions, colour grade and an audio lane are per clip or per lane.
   Drafts can build a few complete Shorts from a video's best moments in one go.

7. **Render.** The server writes a cut list and runs `make_short.py`, which
   assembles the lanes with FFmpeg, burns captions and the title card, and
   writes `workspace/shorts/NNN_name/video.mp4`. The watermark and the card's
   name come from the connected YouTube channel; with none connected they stay
   blank.

8. **Publish.** Connect YouTube once with your own Desktop OAuth client. Upload
   sends the video, title and description as unlisted; you make it public in
   YouTube Studio. From then on the app reads views, likes and audience
   retention for the channel's Shorts, shows them in the Shorts list, and feeds
   them back into step 4.

## Conventions worth knowing

- Every UI file names its dependencies in its first comment. Project edits go
  through `state.project = {...}` followed by `changed()`, which saves and
  records undo.
- Long jobs follow one pattern: a `start_x` route returns a job id, `GET` polls
  it, and the work runs in a daemon thread with progress on the job dict.
- Tests live in `tests/`, one file per behaviour, and run with
  `python3 -m pytest -q tests`. UI logic is tested by slicing a function out
  of its JavaScript file and running it under Node with stubs. Anything that
  talks to YouTube or Ollama is tested through a recorded fake.
- Nothing about a particular channel, person or machine belongs in the code.
  The channel's name and handle come from the connection; paths come from the
  workspace.
