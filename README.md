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

### Browser interface
```powershell
.venv\Scripts\python main.py --gui            # opens http://localhost:8765
.venv\Scripts\python main.py --gui --demo     # same, with the built-in sample scripts
```
The interface runs the same engines as the console, with clicks instead of typing:
- **Create:** one tab per engine. Claude writes the script automatically (see below); if that falls back to copy and paste, press **Read clipboard** after copying Claude's reply, or paste it into the box. Each script field is a text box you edit directly. When the render finishes, the slides, the video and `caption.txt` (which you can edit) appear on the page.
- **Library:** every past run with a thumbnail and its YouTube status. Click one to watch it, edit its caption, open the folder or upload it.
- **Upload:** tick one or more videos, check the preview, then choose **Now**, **Next free slot**, or a date and time.

Keep the console window open while you use it: progress details still print there, and Ctrl+C there stops the interface. `python main.py` without `--gui` still runs the console version.

### How the Claude step works (scripts for A, B and E, E's topic ideas, C's highlight finder)
**Automatic (default):** Synergia asks Claude itself through Claude Code's headless mode (`claude -p`), using your claude.ai Pro login. There's nothing to copy or paste, and it costs nothing extra: each request counts against your Pro usage limits, like a chat on claude.ai. If a reply isn't usable, Synergia sends the correction prompt itself (up to 3 tries). A script takes about 10–20 seconds.
- Needs Claude Code installed and signed in once with your claude.ai account (run `claude` in a terminal and log in).
- To stay free, Synergia only runs it when `claude auth status` reports a claude.ai subscription login, and it never passes an API key to it.
- Settings live in `[claude]` in `config.toml`: model, effort and timeout. Set `mode = "paste"` to always use the manual round trip below.

**Copy and paste (fallback):** if the automatic step fails (not signed in, usage limit reached, timeout), Synergia says why and switches to this:
1. Synergia copies a ready-made prompt to your clipboard.
2. Paste it into claude.ai and send it.
3. Click **Copy** under Claude's reply, return to the terminal and press **Enter**.
4. If the reply isn't usable, a correction prompt is copied for you. Send it in the same chat.

Either way, you then review the script, edit any field (mark highlighted words with `**word**`) and render.

## Engines
| Engine | Input | Output |
|---|---|---|
| **A** Psychology Explainer | Concept | `01_hook.png`…`04_shift.png` + `explainer.mp4` (~10s, with typing sound + music) |
| **B** Random Fact Slideshow | Hook | 6 PNGs (cover + 5 points) for a photo carousel + `slideshow.mp4` (~32s, same slides animated, with typing sound + music) |
| **C** Podcast Clipper | YouTube URL or local `.mp4` | `clip.mp4`, a 9:16 video under 1 minute with the speaker centred and word-highlighted subtitles |
| **D** Brain Test | Nothing - one key press | `brain_test.mp4` (~30-45s): 3-4 timed mini-game rounds. Video only (no PNGs), no Claude needed |
| **E** Which One Are You | Format + topic (Enter = 10 suggestions) | `identity.mp4` (~25-30s): "How many apply to you?" checklist or "Pick one" reveal, + PNGs |

- Every run is saved to `output/<engine>/<date>_<slug>/`, one folder per engine (`A - Psychology Explainer`, `B - Random Fact Slideshow`, `C - Podcast Clipper`, `D - Brain Test`, `E - Which One Are You`), together with `caption.txt` (a TITLE block, then a DESCRIPTION block with the caption, credit and hashtags) and `script.json`.
- **Engine C:** type a range such as `12:30-13:15`, or press Enter to transcribe the whole episode and get 5 suggested moments. The suggestions come from Claude; type `s` to use the offline heuristic instead.
- Transcripts are cached, so re-clipping the same episode is instant.
- **Engine C credits:** for a URL, `caption.txt` gets a credit block with the channel, the video title and the link. For a local file, you're asked who to credit; press Enter to skip. The prefix is `credit_prefix` in `config.toml`.
- **Engine D (Brain Test):** ten games - Stroop test, odd one out, colour vision, memory test, speed count, shell game, quick math, next number, optical illusion and word scramble. Every video mixes 3-4 of them, each round harder than the last, and rotates through all ten so recent games come up less. Everything (grids, colours, words, sums, sequences, illusions, hooks) is generated randomly, and recently used hooks, letter pairs and words are skipped. Timer length, rounds and max length are in `[engine_d]` in `config.toml`.
- **Engine E (Which One Are You):** "How many apply to you?" types out 5-8 signs and ticks each box; "Pick one" shows 3-4 cards (numbers, colours, shapes or doors - Claude picks what fits), a short timer, then one reveal per option. At the topic prompt, press Enter and Claude suggests 10 fresh topics, skipping ones you've already made (`cache/history.json`).
- **Sound effects (D and E):** timer ticks, a "time's up" buzz, a "correct" chime, pops and whooshes are generated in code (no audio files). Volume is `sfx_volume` in `[sound]`.
- **Typing sound (A, B, D and E videos):** real recorded keystrokes (`assets/sounds/keys/`, CC0) are synced to each letter as it appears. To use a different keyboard, swap in your own 16-bit `.wav` files. To change or turn it off, use `[sound]` in `config.toml`.
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

## Autopilot (a week of videos in one go)
Open the **Autopilot** page in the browser interface (`python main.py --gui`). It renders a whole batch, then you review it and schedule it.

1. **Make a batch.** Choose how many of each engine you want. The default is 14 videos, 2 a day for a week: 5 podcast clips, 3 Brain Tests, 2 Psychology Explainers, 2 Fact Slideshows and 2 Which One Are You. Press **Start autopilot**. Here is what happens:
   - **Engine C** takes one episode and cuts all of its clips from it. If you paste an episode URL, it uses that. Otherwise it takes the newest episode it hasn't clipped yet from your **watched channels**. Add channels on the page, e.g. `@ChrisWillx`; they take turns from batch to batch, and uploads shorter than `min_episode_minutes` are skipped. Claude picks the moments plus 2 spares. If no episode is available, the clip slots go to the other engines.
   - **Engines A, B and E:** Claude suggests fresh topics, skipping ones you've already made (`cache/history.json`), then writes each script.
   - **Engine D** needs nothing.

   Each video takes roughly 1–2 minutes, plus the transcription of a new episode. You can close the tab; progress is printed in the console. **Stop after this video** keeps what's already made.
2. **Review.** Every video appears as a card. You can:
   - **Approve** it or **Drop** it.
   - Edit its caption (it saves when you click away).
   - **Regenerate** it: a new script for the same topic, or a new Brain Test.
   - **Replace** a podcast clip with one of the spare moments.

   A video that failed can be retried. Replacing or regenerating deletes the old render, unless it's on YouTube or queued. Dropped videos stay in the Library.
3. **Schedule approved.** Each approved video gets the next free posting slot (`schedule_slots`), which manual uploads also respect. As many as today's quota allows upload right away. The rest wait in the upload queue (`cache/queue.json`), and their slots are already reserved.

**Daily uploads.** Press **Install daily uploads** once. This creates a Windows scheduled task called "Synergia uploads". Every day at `upload_time` (default 10:15, just after YouTube's quota resets at 10:00 Romanian time), it runs `main.py --upload-due`. That uploads the next videos in line, up to `daily_upload_limit` (6). Each one is uploaded days before it goes live.
- If the PC was off at 10:15, the task runs at the next startup. If a video's slot passed meanwhile, it moves to the next free slot.
- The task runs while you're logged in to Windows, without a window. Its log is `cache/autopilot.log`, and the Autopilot page shows the last run.
- **Sign-in:** while your Google OAuth app is in *Testing* mode, the YouTube sign-in expires every 7 days. The background task can't open a browser, so the page shows **Sign in again**. To stop this, set the app's publishing status to **In production** (Google Auth Platform → Audience).

All settings are in `[autopilot]` in `config.toml`: `count`, `mix`, `channels`, `min_episode_minutes`, `daily_upload_limit` and `upload_time`.

## Customising
All brand tokens are in `config.toml`: colours, fonts, safe zone, timings, subtitle size and position, and Whisper models.
