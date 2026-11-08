# Clipbench

A local browser editor that turns long videos into Shorts and publishes them to YouTube.
Everything runs on your Mac. Nothing leaves it except what you choose to upload.

## Features

- Pull in a video from a link, a file, or a live YouTube or Twitch stream
- Find the moments worth cutting from speech, sound, motion and scene cuts, ranked by a local model
- Learn from what you keep, skip and publish, including per-second audience retention
- Cut, caption, lay out and grade on a lane timeline with a phone-shaped preview
- Render 1080x1920 Shorts with FFmpeg and upload them as unlisted, straight from the editor

## Requirements

- macOS with [Homebrew](https://brew.sh)
- Optional: [Ollama](https://ollama.com) for model-ranked suggestions
- Optional: a Google Cloud OAuth client (Desktop app) for YouTube publishing

## Quick start

```sh
./setup.sh
./start.sh
```

Setup installs Python and FFmpeg (`ffmpeg-full`, the build with caption filters) through
Homebrew, uses the first working Python 3.10 or newer it finds, creates `.venv`, and
creates the `workspace/` folder. It is safe to rerun.
The app opens at `http://127.0.0.1:8765`.

```sh
./setup.sh --ai                    # speech to text, vocal separation, person tracking
./start.sh --port 8766 --no-open   # another port, no browser window
```

Run `./setup.sh --ai` before finding clips. Without it there is no speech engine, and
listening either stops with a hint or, if a `whisper` command is on your PATH, runs on
the CPU and takes minutes per video.

## Connect YouTube

1. In Google Cloud Console, enable the YouTube Data API v3 and create an OAuth client of type Desktop app.
2. Save the downloaded JSON as `workspace/data/youtube_client.json`.
3. Choose Connect YouTube in the app and authorize your channel.

The watermark and title card take the channel's name and handle from this connection.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `CLIPBENCH_WORKSPACE` | Where media, projects, Shorts and the database live | `./workspace` |
| `CLIPBENCH_DATA` | Database and account state only | `$CLIPBENCH_WORKSPACE/data` |
| `CLIPBENCH_LLM` | Ollama model used to rank suggestions | best installed model |
| `OLLAMA_HOST` | Ollama server | `http://127.0.0.1:11434` |
| `CLIPBENCH_LOG` | `debug` also logs every API request to `workspace/logs/clipbench.log` | `info` |

## Layout

```
scripts/      server, analysis and renderer (Python)
scripts/clipper_ui/  browser UI (no build step)
tests/        test suite
tools/        setup, relocation and packaging
docs/         how the pieces fit together
workspace/    your media and data, ignored by git
```

See [docs/how-it-works.md](docs/how-it-works.md) for the architecture and the path from a video to a published Short.

## Development

```sh
.venv/bin/python -m unittest discover -s tests
```

UI tests need Node.js (`brew install node`). Some tests render short synthetic media with FFmpeg.

## Packaging

```sh
python3 tools/starter_pack.py clipbench-starter.zip
```

Exports the committed application files only. No media, credentials or local data are included.
