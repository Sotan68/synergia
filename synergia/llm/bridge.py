"""Zero-cost LLM bridge: copy a prompt to the clipboard -> user runs it in Claude Pro -> read reply back."""
from __future__ import annotations

import json
import re
from typing import Callable

import pyperclip
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from synergia.config import CFG
from synergia.llm.prompts import fix_prompt

console = Console()

Validator = Callable[[dict], list[str]]


class Cancelled(Exception):
    pass


class Skipped(Exception):
    pass


# ---------------------------------------------------------------- JSON extraction
def extract_json(text: str) -> dict:
    """Find and parse the first JSON object in a Claude reply (fenced or not)."""
    candidates = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.S | re.I)
    candidates.append(text)
    last_err: Exception | None = None
    for c in candidates:
        start = c.find("{")
        while start != -1:
            chunk = c[start:]
            chunk = chunk.replace("“", '"').replace("”", '"')
            chunk = re.sub(r",(\s*[}\]])", r"\1", chunk)  # trailing commas
            try:
                obj, _ = json.JSONDecoder().raw_decode(chunk)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError as e:
                last_err = e
            start = c.find("{", start + 1)
    raise ValueError(f"No valid JSON object found ({last_err})" if last_err
                     else "No JSON object found in the reply")


# ---------------------------------------------------------------- validation helpers
def words(s: str) -> int:
    return len(re.sub(r"\*\*", "", s or "").split())


def check_text(data: dict, key: str, max_words: int, errors: list[str],
               warnings: list[str] | None = None) -> None:
    v = data.get(key)
    if not isinstance(v, str) or not v.strip():
        errors.append(f'"{key}" is missing or empty')
        return
    n = words(v)
    if n > max_words * 1.5:
        errors.append(f'"{key}" has {n} words; the limit is {max_words}')
    elif n > max_words and warnings is not None:
        warnings.append(f'"{key}" is {n} words (target {max_words})')


def normalize_common(data: dict) -> dict:
    tags = data.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.split()
    data["hashtags"] = ["#" + t.lstrip("#").replace(" ", "") for t in tags if str(t).strip()]
    data["caption"] = str(data.get("caption") or "").strip()
    # Post title (for the platform's title field): plain text, no markup.
    data["title"] = re.sub(r"\*\*", "", str(data.get("title") or "")).strip().strip('"')
    return data


def parse_reply(reply: str, validator: Validator) -> tuple[dict | None, list[str]]:
    """(data, []) if the reply holds valid JSON that passes the validator, else (None, errors)."""
    try:
        data = extract_json(reply)
    except ValueError as e:
        return None, [str(e)]
    errors = validator(data)
    return (None, errors) if errors else (data, [])


# ---------------------------------------------------------------- clipboard round-trip
def _read_manual() -> str:
    console.print("[dim]Paste Claude's reply below, then type [bold]END[/bold] on its own line:[/dim]")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "END":
            break
        lines.append(line)
    return "\n".join(lines)


def _copy(text: str) -> bool:
    try:
        pyperclip.copy(text)
        return True
    except pyperclip.PyperclipException:
        return False


def ask_claude(prompt: str, validator: Validator, title: str = "Claude",
               allow_skip: bool = False, max_rounds: int = 4) -> dict:
    """Get a reply that passes validation: automatically via Claude Code when available,
    otherwise (or if that fails) through the clipboard round-trip.

    Raises Cancelled on 'q', Skipped on 's' (only when allow_skip).
    """
    from synergia.llm import claude_code

    current = prompt
    if claude_code.available():
        try:
            with console.status(f"[yellow]{title}: asking Claude (Claude Code)…") as st:
                return claude_code.ask_auto(prompt, validator,
                                            on_status=lambda m: st.update(f"[yellow]{title}: {m}"))
        except claude_code.ClaudeCodeError as e:
            console.print(f"[yellow]{escape(str(e))}[/yellow]\n[dim]Falling back to copy and paste.[/dim]")
            current = e.last_prompt or prompt

    CFG.output.cache_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = CFG.output.cache_dir / "last_prompt.txt"
    for _ in range(max_rounds):
        prompt_file.write_text(current, encoding="utf-8")
        copied = _copy(current)
        msg = ("[bold green]Prompt copied to your clipboard.[/bold green]\n" if copied else
               f"[yellow]Clipboard unavailable — open {prompt_file} and copy it.[/yellow]\n")
        msg += ("1. Paste it into a Claude chat (claude.ai) and send.\n"
                "2. Copy Claude's whole reply (the copy button under the message).\n"
                "3. Come back here and press [bold]Enter[/bold].")
        console.print(Panel(msg, title=f"✦ {title}", border_style="yellow"))
        opts = "[Enter]=read clipboard  p=paste manually  c=copy prompt again"
        if allow_skip:
            opts += "  s=skip"
        opts += "  q=cancel"

        while True:
            choice = Prompt.ask(f"[dim]{opts}[/dim]", default="", show_default=False).strip().lower()
            if choice == "q":
                raise Cancelled()
            if choice == "s" and allow_skip:
                raise Skipped()
            if choice == "c":
                _copy(current)
                console.print("[green]Copied again.[/green]")
                continue
            if choice == "p":
                reply = _read_manual()
            else:
                try:
                    reply = pyperclip.paste()
                except pyperclip.PyperclipException:
                    reply = _read_manual()
                if reply.strip() == current.strip():
                    console.print("[yellow]The clipboard still holds the prompt — copy Claude's reply first.[/yellow]")
                    continue
            if not reply.strip():
                console.print("[yellow]Nothing to read. Try again.[/yellow]")
                continue
            break

        data, errors = parse_reply(reply, validator)
        if data is not None:
            return data
        console.print(Panel("\n".join(f"• {e}" for e in errors), title="Reply needs a fix",
                            border_style="red"))
        current = fix_prompt(errors, reply)
        console.print("[dim]A correction prompt will be copied — send it in the same Claude chat.[/dim]")
    raise Cancelled("Too many invalid replies.")


# ---------------------------------------------------------------- review / edit
def review(data: dict, fields: list[tuple[str, str]], title: str = "Script") -> str:
    """Show fields; returns 'ok', 'regen'. Edits are applied in-place. fields = [(label, key-path)]."""
    while True:
        t = Table(title=title, show_lines=True, border_style="yellow")
        t.add_column("#", style="dim", width=3)
        t.add_column("Field", style="bold")
        t.add_column("Text")
        for i, (label, path) in enumerate(fields, 1):
            t.add_row(str(i), label, str(get_path(data, path)))
        console.print(t)
        c = Prompt.ask("[dim][Enter]=render  <number>=edit field  r=regenerate  q=cancel[/dim]",
                       default="", show_default=False).strip().lower()
        if c == "":
            return "ok"
        if c == "q":
            raise Cancelled()
        if c == "r":
            return "regen"
        if c.isdigit() and 1 <= int(c) <= len(fields):
            label, path = fields[int(c) - 1]
            console.print(f"[dim]Current:[/dim] {get_path(data, path)}")
            new = Prompt.ask(f"New {label} (use **word** to highlight)").strip()
            if new:
                set_path(data, path, new)


def get_path(d, path: str):
    """data['points'][0]['text'] for path 'points.0.text'."""
    for p in path.split("."):
        d = d[int(p)] if p.isdigit() else d[p]
    return d


def set_path(d, path: str, value) -> None:
    parts = path.split(".")
    for p in parts[:-1]:
        d = d[int(p)] if p.isdigit() else d[p]
    last = parts[-1]
    if last.isdigit():
        d[int(last)] = value
    else:
        d[last] = value
