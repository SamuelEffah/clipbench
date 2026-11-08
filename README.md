# Clipbench

Local browser video editor. The application code lives in `scripts/`, the browser
UI in `scripts/clipper_ui/`, development checks in `tests/`, and installation and
distribution helpers in `tools/`. No Node build step is required to run the app.

## Install and start (macOS)

Install [Homebrew](https://brew.sh) first. Open Terminal in this folder and run:

```sh
./setup.sh
./start.sh
```

Setup installs Homebrew Python 3.11 and FFmpeg, creates an isolated `.venv`, installs
core Python dependencies, creates runtime folders, and supplies a neutral avatar
only when no avatar exists. It is safe to rerun and preserves existing projects
and media. Internet access is required. Python packages use compatible ranges;
this is not a fully locked/reproducible environment.

The welcome page opens at `http://127.0.0.1:8765`. Connect YouTube or choose
**Skip for now** to open the editor. You can also go directly to `/editor`.
If YouTube is not configured, the welcome page explains where to place your
Desktop OAuth client JSON. The locally bundled Mars texture rotates on a 3D
sphere; reduced-motion preferences show a still sphere, and browsers without
WebGL keep the original photograph. Stop the server with Ctrl+C.
Use `./start.sh --port 8766 --no-open` to change the port or skip browser opening.
Launch through `start.sh` so child processes find the virtual environment tools.
The renderer currently uses macOS fonts and hardware encoder options; Windows
and Linux are not supported by this starter.

For transcription, vocal separation, and person tracking dependencies:

```sh
./setup.sh --ai
```

AI packages are optional and substantially larger. AI setup also downloads the
YOLO person-tracking model into `scripts/models/`; speech and separation models
download when first used. MLX speech is installed only on Apple Silicon. Review
the model and dependency licenses for your intended use.
AI suggestions also require a separately configured local Ollama installation;
`OLLAMA_HOST` and `CLIPBENCH_LLM` can select its server and model. YouTube publishing
requires your own Desktop OAuth client JSON at `workspace/data/youtube_client.json` and
account authorization in the app. These services and credentials are not bundled.

## Local data and source control

Only application code, tests, tooling, and development documentation belong in
Git. Media, channel images, cut lists, narration, projects, rendered Shorts,
databases, credentials, downloaded models, environments, and caches are ignored.
Folders are created by setup rather than committed as empty placeholder files.

Everything the app downloads, makes or remembers lives under `workspace/`
(move it with `CLIPBENCH_WORKSPACE`). Put source videos in `workspace/clips/`,
extra footage in `workspace/broll/`, and audio in `workspace/audio/` or
`workspace/music/`. Projects and account state live in `workspace/data/`
(override with `CLIPBENCH_DATA`); cut-list exports land in `workspace/projects/`
and rendered videos in `workspace/shorts/`. Back up the workspace separately:
Git does not back it up. Replace `workspace/channel/avatar.png` with your own
image when needed. An install laid out the old way, with those folders beside
the code, is moved into the workspace by `./setup.sh` or `python3 tools/relocate.py`.

## Give someone a starter pack

After committing application changes, run:

```sh
python3 tools/starter_pack.py dist/clipbench-starter.zip
```

The exporter reads committed `HEAD` and includes only application sources, setup
requirements, the README, and tools. It excludes `.git`, personal data, media,
credentials, mockups, tests, development notes, and downloaded model weights.
Existing archives are never overwritten. The recipient unzips the archive,
opens Terminal in `clipbench/`, and runs `./setup.sh`, then `./start.sh`.

## Development checks

```sh
.venv/bin/python -m unittest discover -s tests
```

UI regression tests also need Node.js (`brew install node`). Some tests use
FFmpeg with temporary synthetic media. Setup and launch checks do not start the
server or scan your media until `start.sh` launches the app.

### Faster clipping workflow

- **Live moments:** use **Mark moment** (or **Shift+M**) while watching a stream. Gold markers bookmark the current playback time without cutting a clip. Click a marker to seek, or focus it and press Delete to remove it. Markers are stored in this browser for each project and stream, up to 200. Only markers still inside the available footage appear; live Twitch channels cannot rewind.
- **Transcript clips:** in Short mode, select words in the live captions transcript, then choose **Create clip**. The selection is added to the Clips bank using its speech timestamps; the Short remains unchanged. Speech timing must already be available. This also works with Static captions when timing exists.
- **Session restore:** reopening a project restores its mode, selected clip, source/playhead, and timeline zoom/scroll. Playback restores paused. View state stays in this browser; live streams are not automatically reconnected.

### Short presets and suggestion review

In **Short → Look → Presets**, click **+**, name a preset and choose **Save** to save layout, format, caption appearance, watermark, background and loudness settings in this browser. Saving the same name replaces that preset. Choose a saved preset to immediately use it on the current Short and its main-lane captions; media, caption words and music files stay in place. Applying is undoable. Presets are local to this browser, so they do not travel with a project.

In **Suggest clips**, click a moment to preview it, mark **Keep** or **Skip**, then choose **Add kept** to add the selected moments together. Click a decision again to clear it. Existing clips are not added twice; review decisions reset when suggestions are requested again.
