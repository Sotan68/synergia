"""Upload a run folder's video to YouTube (as a Short) via the official YouTube Data API v3.

One-time setup is in the README ("Uploading to YouTube"). In short: a Google Cloud project with
the YouTube Data API v3 enabled, an OAuth "Desktop app" client saved as secrets/client_secret.json,
then the first upload opens a browser to sign in and caches the token in secrets/.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone

from synergia.config import CFG
from synergia.publish import Post, record

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TITLE_MAX = 100            # characters
DESCRIPTION_MAX = 5000     # bytes (UTF-8)
TAGS_MAX = 500             # characters, all tags together
SHORTS_MAX_SECONDS = 180
RETRY_STATUSES = (500, 502, 503, 504)
MAX_RETRIES = 6


class NotConfigured(RuntimeError):
    pass


def _paths():
    yt = CFG.youtube
    return CFG.root / yt.client_secret, CFG.root / yt.token_file


def is_configured() -> bool:
    secret, token = _paths()
    return secret.is_file() or token.is_file()


# ---------------------------------------------------------------- metadata

def _clean(s: str) -> str:
    return s.replace("<", "").replace(">", "")   # YouTube rejects angle brackets in title/description


def _truncate_words(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    cut = s[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return cut + "…"


def _truncate_bytes(s: str, limit: int) -> str:
    b = s.encode("utf-8")
    return s if len(b) <= limit else b[:limit].decode("utf-8", "ignore").rstrip()


def _tags(hashtags: list[str]) -> list[str]:
    out, used = [], 0
    for t in hashtags:
        cost = len(t) + (1 if out else 0)   # tags are comma-joined for the limit
        if used + cost > TAGS_MAX:
            break
        out.append(t)
        used += cost
    return out


def build_body(post: Post, privacy: str, publish_at: datetime | None = None) -> dict:
    """publish_at: YouTube keeps the video private until then, then makes it public."""
    yt = CFG.youtube
    title = _truncate_words(_clean(post.title).strip(), TITLE_MAX) or "Untitled"
    status = {
        "privacyStatus": "private" if publish_at else privacy,   # the API requires private to schedule
        "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": bool(yt.synthetic_media),
    }
    if publish_at:
        status["publishAt"] = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "snippet": {
            "title": title,
            "description": _truncate_bytes(_clean(post.description), DESCRIPTION_MAX),
            "tags": _tags(post.hashtags),
            "categoryId": str(yt.category_id),
            "defaultLanguage": yt.language,
            "defaultAudioLanguage": yt.language,
        },
        "status": status,
    }


def shorts_warnings(info: dict) -> list[str]:
    """Reasons YouTube won't treat this video as a Short (it still uploads as a normal video)."""
    w = []
    if info["height"] < info["width"]:
        w.append(f"video is landscape ({info['width']}x{info['height']}); Shorts must be vertical or square")
    if info["duration"] > SHORTS_MAX_SECONDS:
        w.append(f"video is {info['duration']:.0f}s; Shorts must be {SHORTS_MAX_SECONDS}s or shorter")
    return w


# ---------------------------------------------------------------- auth + upload

def _credentials():
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    secret, token = _paths()
    creds = None
    if token.is_file():
        creds = Credentials.from_authorized_user_file(str(token), SCOPES)
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                creds = None   # revoked, or a 7-day "Testing"-mode token: sign in again
    if creds is None or not creds.valid:
        if not secret.is_file():
            raise NotConfigured(
                f"YouTube isn't set up: {secret} not found. See 'Uploading to YouTube' in README.md.")
        flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True,
                                      authorization_prompt_message="Opening browser to sign in to YouTube…",
                                      success_message="Signed in. You can close this tab and return to Synergia.")
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _friendly(err) -> str:
    text = str(err)
    for key, msg in (
        ("quotaExceeded", "Daily YouTube API quota used up (about 6 uploads/day). It resets at midnight Pacific time."),
        ("uploadLimitExceeded", "Your channel hit YouTube's upload limit for now. Try again later."),
        ("youtubeSignupRequired", "This Google account has no YouTube channel yet. Create one at youtube.com first."),
        ("forbidden", "YouTube refused the upload (403). Check the account has a channel and the API is enabled."),
    ):
        if key in text:
            return msg
    return text


def is_limit_error(err: BaseException) -> bool:
    """Daily API quota or channel upload limit: retrying other videos today will fail too."""
    text = str(err)
    return any(k in text for k in ("quota", "upload limit", "quotaExceeded", "uploadLimitExceeded"))


def upload(post: Post, privacy: str | None = None, publish_at: datetime | None = None,
           on_progress: Callable[[float], None] | None = None) -> dict:
    """Upload post.video and record it in posted.json.

    Returns {'id', 'url', 'privacy', 'file'} plus 'publish_at' (local ISO time) if the schedule
    was accepted, or 'schedule_dropped': True if YouTube ignored it (unaudited API project).
    """
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    privacy = privacy or CFG.youtube.privacy
    service = build("youtube", "v3", credentials=_credentials(), cache_discovery=False)
    media = MediaFileUpload(str(post.video), mimetype="video/mp4",
                            chunksize=8 * 1024 * 1024, resumable=True)
    request = service.videos().insert(part="snippet,status",
                                      body=build_body(post, privacy, publish_at),
                                      media_body=media,
                                      notifySubscribers=bool(CFG.youtube.notify_subscribers))
    response, retries = None, 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status and on_progress:
                on_progress(status.progress())
        except HttpError as e:
            if e.resp.status in RETRY_STATUSES and retries < MAX_RETRIES:
                retries += 1
                time.sleep(min(2 ** retries, 60))
                continue
            raise RuntimeError(_friendly(e)) from e
        except (ConnectionError, TimeoutError, OSError):
            if retries >= MAX_RETRIES:
                raise
            retries += 1
            time.sleep(min(2 ** retries, 60))
    if on_progress:
        on_progress(1.0)

    vid = response["id"]
    st = response.get("status", {})
    result = {"id": vid, "url": f"https://youtube.com/shorts/{vid}",
              "privacy": st.get("privacyStatus", privacy), "file": post.video.name}
    if publish_at:
        if st.get("publishAt"):
            result["publish_at"] = publish_at.astimezone().isoformat(timespec="minutes")
        else:
            result["schedule_dropped"] = True
    record(post.folder, "youtube", result)
    return result
