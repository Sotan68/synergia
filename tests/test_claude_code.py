"""Checks for the automatic Claude Code step. No real Claude calls. Run: .venv\\Scripts\\python -m pytest tests"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from synergia import demo  # noqa: E402
from synergia.engines import psychology  # noqa: E402
from synergia.llm import claude_code as cc  # noqa: E402


class Done:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


@pytest.fixture
def fake(monkeypatch):
    """Fake `claude`: records each call; `replies` holds what `claude -p` prints."""
    calls, replies = [], []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        if cmd[1:3] == ["auth", "status"]:
            return Done(json.dumps({"loggedIn": True, "authMethod": "claude.ai"}))
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(cc, "_exe", lambda: "claude")
    monkeypatch.setattr(cc, "_login_ok", None)
    monkeypatch.setattr(cc.subprocess, "run", run)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-never-reach-claude")
    return calls, replies


def ok(text):
    return Done(json.dumps({"type": "result", "is_error": False, "result": text}))


def test_ask_is_free_and_uses_stdin(fake):
    calls, replies = fake
    replies.append(ok('{"a": 1}'))
    assert cc.ask("hello") == '{"a": 1}'
    cmd, kw = calls[-1]
    assert cmd[:2] == ["claude", "-p"] and "--bare" not in cmd
    assert cmd[cmd.index("--tools") + 1] == ""
    assert kw["input"] == "hello"
    for env_kw in (kw, calls[0][1]):      # the auth check and the call itself
        assert not any(k in env_kw["env"] for k in cc.PAID_ENV)


def test_refuses_non_subscription_login(fake, monkeypatch):
    calls, _ = fake
    monkeypatch.setattr(cc.subprocess, "run",
                        lambda cmd, **kw: Done(json.dumps({"loggedIn": True, "authMethod": "api_key"})))
    with pytest.raises(cc.ClaudeCodeError, match="billed"):
        cc.ask("hello")


def test_errors(fake):
    _, replies = fake
    replies += [Done(json.dumps({"is_error": True, "result": "You've hit your usage limit"}), returncode=1),
                Done("not json", returncode=1, stderr="boom"),
                subprocess.TimeoutExpired("claude", 5)]
    with pytest.raises(cc.ClaudeCodeError, match="usage limit"):
        cc.ask("x")
    with pytest.raises(cc.ClaudeCodeError, match="boom"):
        cc.ask("x")
    with pytest.raises(cc.ClaudeCodeError, match="didn't answer") as e:
        cc.ask("x")
    assert e.value.last_prompt == "x"


def test_ask_auto_fixes_bad_reply():
    sent = []
    replies = ["no json here", "```json\n" + json.dumps(demo.PSYCHOLOGY) + "\n```"]

    def asker(p):
        sent.append(p)
        return replies.pop(0)

    data = cc.ask_auto("write it", psychology.validate, asker=asker)
    assert data["concept"] == demo.PSYCHOLOGY["concept"]
    assert sent[0] == "write it" and "could not be used" in sent[1]


def test_ask_auto_gives_up_with_last_prompt():
    with pytest.raises(cc.ClaudeCodeError) as e:
        cc.ask_auto("write it", psychology.validate, max_rounds=3, asker=lambda p: "still no json")
    assert "could not be used" in e.value.last_prompt
