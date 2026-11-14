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
| **A** Psychology Explainer | Concept | `01_hook.png`…`04_shift.png` + `explainer.mp4` (~10s, with typing sound + music) |
| **B** Random Fact Slideshow | Hook | 6 PNGs (cover + 5 points) for a photo carousel + `slideshow.mp4` (~32s, same slides animated, with typing sound + music) |
| **C** Podcast Clipper | YouTube URL or local `.mp4` | `clip.mp4`, a 9:16 video under 1 minute with the speaker centred and word-highlighted subtitles |

- Every run is saved to `output/<engine>/<date>_<slug>/`, one folder per engine (`A - Psychology Explainer`, `B - Random Fact Slideshow`, `C - Podcast Clipper`), together with `caption.txt` (a TITLE block, then a DESCRIPTION block with the caption, credit and hashtags) and `script.json`.
- **Engine C:** type a range such as `12:30-13:15`, or press Enter to transcribe the whole episode and get 5 suggested moments. The suggestions come from Claude; type `s` to use the offline heuristic instead.
- Transcripts are cached, so re-clipping the same episode is instant.
- **Engine C credits:** for a URL, `caption.txt` gets a credit block with the channel, the video title and the link. For a local file, you're asked who to credit; press Enter to skip. The prefix is `credit_prefix` in `config.toml`.
- **Typing sound (A and B videos):** real recorded keystrokes (`assets/sounds/keys/`, CC0) are synced to each word as it appears. To use a different keyboard, swap in your own 16-bit `.wav` files. To change or turn it off, use `[sound]` in `config.toml`.
- **Background music (A and B videos):** each video gets a random CC0 lofi track from `assets/music/`, volume-matched, faded in and out, and mixed under the typing. Credits are in `assets/music/LICENSE.txt`, and the track used is saved as `music` in `script.json`. To add your own tracks, drop `.mp3`/`.ogg` files into that folder. Volume and on/off are in `[sound]` in `config.toml`.
- **Clip length (C):** every clip stays under 1 minute. Anything longer is trimmed at the last sentence that ends in time (`hard_max_seconds`).
- **Engines A and B:** every slide has a footer with the Overlap logo mark and the SYNERGIA wordmark. It lines up with the text: left-aligned on most slides, centred on the centred "Shift" slide.

## Uploading to YouTube
Synergia can upload a rendered video as a YouTube Short through the official YouTube Data API. It's free, and nothing is posted without you confirming it.

**One-time setup (about 10 minutes):**
1. Go to [console.cloud.google.com](https://console.cloud.google.com), create a project, and enable **YouTube Data API v3** (APIs & Services → Library).
2. Under **Google Auth Platform → Branding/Audience**, configure the consent screen as **External** and add your own Google account as a **test user**.
3. Under **Clients**, create an OAuth client of type **Desktop app**. Download its JSON and save it as `secrets/client_secret.json` (the `secrets/` folder is git-ignored).
4. In Synergia, press **U** and pick a video. A browser opens once to sign in; the token is cached in `secrets/youtube_token.json`.

**How it works:**
- After each render you're asked whether to upload it. You can also press **U** in the menu to pick any of your recent videos (✓ marks ones already uploaded).
- The title and description come from `caption.txt`, so edit that file to change them. The hashtags also become tags.
- Before anything is sent, you see a preview with the title, description, tags, size, length and privacy, and you confirm it.
- Each upload is logged to `posted.json` in the run folder, and you're warned before uploading the same video twice.
- **Scheduling:** at "When?", press Enter to post now, type **n** for the next free posting slot, or type a time such as `tomorrow 18:00`, `fri 9:30`, `2026-12-01 08:00` or `3.12 10:00`. The video uploads straight away as private and YouTube makes it public at that time, so your PC can be off. Posting slots are `schedule_slots` in `config.toml`.
- **Batch scheduling:** in the **U** menu, pick several videos (e.g. `1 2 3`) and answer **n**. Each video takes the next free slot, and slots that are already booked are skipped. The list shows when each scheduled video goes live.
- Settings live in `[youtube]` in `config.toml`: privacy, category, notifying subscribers, the AI-content label, and whether to ask after each render.

**Limits to know:**
- **Videos stay private at first.** Google forces uploads from API projects that haven't been audited to private, and this probably cancels a schedule too. Synergia tells you if YouTube ignored the schedule. Until the audit, set the time in YouTube Studio (Visibility → Schedule), or apply for the [API audit](https://support.google.com/youtube/contact/yt_api_form) to lift this.
- **About 6 uploads per day.** This limit counts uploads, not go-live times, so you can schedule 6 a day as far ahead as you like. The free quota is 10,000 units and each upload costs 1,600.
- **Sign-in expires weekly while the app is in "Testing" mode.** Synergia simply asks you to sign in again. To stop this, set the app's publishing status to **In production** on the Audience page.

## Customising
All brand tokens are in `config.toml`: colours, fonts, safe zone, timings, subtitle size and position, and Whisper models.
