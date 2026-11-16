"""Ask Claude automatically through Claude Code's headless mode (`claude -p`) on your claude.ai login.

Free by construction: it only runs when Claude Code is signed in with a claude.ai subscription
(Pro/Max), the child process never sees an API key, and `--bare` (API-key-only auth) is never used.
Each call counts against your plan's usage limits, like a chat on claude.ai.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Callable

from synergia.config import CFG

SYSTEM_PROMPT = ("You are a writer for a short-form video brand. Answer the request directly and "
                 "follow its output format exactly. Do not ask questions or add commentary.")
# Variables that would make Claude Code bill an API account instead of using the subscription.
PAID_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")


class ClaudeCodeError(RuntimeError):
    def __init__(self, message: str, last_prompt: str = ""):
        super().__init__(message)
        self.last_prompt = last_prompt


def _cfg(name: str, default):
    return getattr(getattr(CFG, "claude", None), name, default)


def _exe() -> str | None:
    return shutil.which("claude")


def available() -> bool:
    """Automatic mode is switched on and Claude Code is installed."""
    return _cfg("mode", "code") == "code" and _exe() is not None


def _env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in PAID_ENV}


_login_ok: bool | None = None   # checked once per run


def check_login() -> None:
    """Raise unless Claude Code is signed in with a claude.ai subscription (so calls cost nothing extra)."""
    global _login_ok
    if _login_ok:
        return
    try:
        r = subprocess.run([_exe() or "claude", "auth", "status"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60, env=_env())
        status = json.loads(r.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        raise ClaudeCodeError(f"Couldn't check the Claude Code login ({e}).") from e
    if not status.get("loggedIn"):
        raise ClaudeCodeError("Claude Code isn't signed in. Run `claude` once in a terminal and log in "
                              "with your claude.ai account.")
    if status.get("authMethod") != "claude.ai":
        raise ClaudeCodeError(f"Claude Code is signed in with {status.get('authMethod')!r}, not a claude.ai "
                              "subscription, so calls could be billed. Log in with your claude.ai account.")
    _login_ok = True


def ask(prompt: str) -> str:
    """Send one prompt, return Claude's text reply. Raises ClaudeCodeError."""
    exe = _exe()
    if not exe:
        raise ClaudeCodeError("Claude Code (`claude`) isn't installed or isn't on PATH.", prompt)
    check_login()
    cmd = [exe, "-p", "--output-format", "json", "--tools", "", "--no-session-persistence",
           "--safe-mode", "--system-prompt", SYSTEM_PROMPT]
    if _cfg("model", ""):
        cmd += ["--model", _cfg("model", "")]
    if _cfg("effort", ""):
        cmd += ["--effort", _cfg("effort", "")]
    workdir = CFG.output.cache_dir / "claude"     # empty folder: nothing for Claude Code to pick up
    workdir.mkdir(parents=True, exist_ok=True)
    timeout = float(_cfg("timeout_seconds", 300))
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, cwd=workdir, env=_env())
    except subprocess.TimeoutExpired as e:
        raise ClaudeCodeError(f"Claude didn't answer within {timeout:.0f}s.", prompt) from e
    except OSError as e:
        raise ClaudeCodeError(f"Couldn't start Claude Code ({e}).", prompt) from e
    try:
        out = json.loads(r.stdout)
    except ValueError:
        detail = (r.stderr or r.stdout).strip().splitlines()
        raise ClaudeCodeError(f"Claude Code failed: {detail[-1] if detail else f'exit code {r.returncode}'}",
                              prompt) from None
    text = str(out.get("result") or "")
    if out.get("is_error") or r.returncode != 0:
        msg = text or out.get("subtype") or f"exit code {r.returncode}"
        if "limit" in msg.lower():
            msg = f"{msg} (your Pro usage limit; try again later or paste manually)"
        raise ClaudeCodeError(f"Claude Code: {msg}", prompt)
    if not text.strip():
        raise ClaudeCodeError("Claude returned an empty reply.", prompt)
    return text


def ask_auto(prompt: str, validator: Callable[[dict], list[str]], max_rounds: int = 3,
             on_status: Callable[[str], None] | None = None, asker: Callable[[str], str] = ask) -> dict:
    """Ask, validate, send a correction prompt if needed. Returns valid data or raises ClaudeCodeError
    (its last_prompt is what to continue with by hand)."""
    from synergia.llm.bridge import parse_reply
    from synergia.llm.prompts import fix_prompt

    current = prompt
    errors: list[str] = []
    for i in range(max_rounds):
        if on_status:
            on_status("Asking Claude…" if i == 0 else f"Asking Claude to fix the reply (try {i + 1})…")
        reply = asker(current)
        data, errors = parse_reply(reply, validator)
        if data is not None:
            return data
        current = fix_prompt(errors, reply)
    raise ClaudeCodeError("Claude's reply still had problems after "
                          f"{max_rounds} tries: {'; '.join(errors[:3])}", current)
