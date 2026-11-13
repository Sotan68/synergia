# SYNERGIA — Zero-Cost Short-Form Content Engine

Everything runs locally. There are no paid APIs. Script writing uses a clipboard round trip with your Claude Pro chat.

## Setup (once)
```powershell
py -3.13 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python setup_assets.py      # Inter font + YuNet face model
```
You also need:
- **ffmpeg** on your PATH.
- **Node.js** (or deno), for YouTube downloads.

On an NVIDIA GPU, Whisper runs on CUDA automatically and falls back to the CPU if CUDA isn't available.

## Run
```powershell
.venv\Scripts\python main.py            # normal
.venv\Scripts\python main.py --demo     # A/B with built-in sample scripts (no Claude step)
.venv\Scripts\python main.py --debug    # safe-zone overlay, tracking debug video, tracebacks
```

### How the Claude step works (Engines A and B, plus C's highlight finder)
1. Synergia copies a ready-made prompt to your clipboard.
2. Paste it into claude.ai and send it.
3. Click **Copy** under Claude's reply, return to the terminal and press **Enter**.
4. If the reply isn't usable, a correction prompt is copied for you. Send it in the same chat.
5. Review the script, edit any field (mark highlighted words with `**word**`), then press Enter to render.

## Engines
| Engine | Input | Output |
|---|---|---|
| **A** Psychology Explainer | Concept | `01_hook.png`…`04_shift.png` + `explainer.mp4` (~10s, silent) |
| **B** Random Fact Slideshow | Hook | 6 PNGs (cover + 5 points) for a photo carousel + `slideshow.mp4` (~32s, same slides animated) |
| **C** Podcast Clipper | YouTube URL or local `.mp4` | `clip.mp4`, a 9:16 video with the speaker centred and word-highlighted subtitles |

- Every run is saved to `output/<engine>/<date>_<slug>/`, one folder per engine (`A - Psychology Explainer`, `B - Random Fact Slideshow`, `C - Podcast Clipper`), together with `caption.txt` (caption and hashtags) and `script.json`.
- **Engine C:** type a range such as `12:30-13:15`, or press Enter to transcribe the whole episode and get 5 suggested moments. The suggestions come from Claude; type `s` to use the offline heuristic instead.
- Transcripts are cached, so re-clipping the same episode is instant.
- **Engine C credits:** for a URL, `caption.txt` gets a credit block with the channel, the video title and the link. For a local file, you're asked who to credit; press Enter to skip. The prefix is `credit_prefix` in `config.toml`.
- **Engines A and B:** every slide has a footer with the Overlap logo mark and the SYNERGIA wordmark. It lines up with the text: left-aligned on most slides, centred on the centred "Shift" slide.

## Customising
All brand tokens are in `config.toml`: colours, fonts, safe zone, timings, subtitle size and position, and Whisper models.
