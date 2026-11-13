"""Prompt templates for the Claude Pro clipboard bridge."""
from __future__ import annotations

BRAND_VOICE = """You are the head writer for SYNERGIA, a faceless short-form brand (TikTok, Reels, Shorts)
about human psychology, life advice and real experiences.
Voice: minimalist, direct, second-person ("you"), slightly provocative, emotionally sharp.
No fluff, no emojis, no hashtags inside the text, no clichés like "In today's world".
Every sentence must be short and readable on a phone screen in under 3 seconds."""

JSON_RULES = """OUTPUT RULES:
- Reply with ONE ```json code block and nothing else.
- Valid JSON only (double quotes, no trailing commas, no comments).
- In text fields, wrap the 1-2 most important words in **double asterisks** — they get highlighted in the accent color.
  Never highlight more than 3 words per field."""


def psychology_prompt(concept: str) -> str:
    return f"""{BRAND_VOICE}

TASK: Write a 10-second psychology explainer about: "{concept}"

Use this exact 4-step formula:
1. hook_line — the "why it matters" line that follows "<Concept> explained in 10 seconds:" (max 10 words).
2. gotcha — "The Mirror": a hyper-relatable scenario that makes the viewer feel caught (max 40 words).
3. mechanism — how the brain tricks them, in plain language (max 35 words).
4. shift — one punchy concluding sentence that reframes everything (max 20 words).

TONE REFERENCE (concept "The Spotlight Effect"):
- hook_line: "Why you **overthink** everything you do."
- gotcha: "Think about that slightly awkward thing you said three days ago. You've replayed it 20 times. Meanwhile, the person you said it to **forgot it** 10 seconds later."
- mechanism: "Because you are the center of your own universe, your brain assumes everyone is **watching and judging** you as closely as you watch yourself."
- shift: "Nobody is keeping score of your mistakes — they're too busy worrying about **how they look to you**."

{JSON_RULES}

JSON SCHEMA:
```json
{{
  "concept": "{concept}",
  "title": "post title for TikTok / Reels / Shorts: max 70 characters, curiosity hook, no hashtags, no emojis, no asterisks",
  "hook_line": "...",
  "gotcha": "...",
  "mechanism": "...",
  "shift": "...",
  "caption": "1-2 sentence post caption that drives comments (no hashtags)",
  "hashtags": ["#psychology", "...", "5-8 relevant hashtags"]
}}
```"""


def listicle_prompt(hook: str) -> str:
    return f"""{BRAND_VOICE}

TASK: Write a 6-slide photo carousel. Slide 1 is the cover hook; slides 2-6 are 5 points.
User's hook: "{hook}"

Rules:
- cover_title: the hook, tightened to max 12 words (keep the number 5 if present).
- cover_subtitle: tiny teaser under the title, max 6 words (e.g. "Number 4 hurts the most.").
- Each point: "title" max 8 words (the punchline), "body" max 22 words (the human truth behind it).
- Order the points so the strongest emotional hit is #4 or #5.
- Concrete and specific beats generic. Write like someone who has lived it.

{JSON_RULES}

JSON SCHEMA:
```json
{{
  "title": "post title for TikTok / Reels / Shorts: max 70 characters, curiosity hook, no hashtags, no emojis, no asterisks",
  "cover_title": "...",
  "cover_subtitle": "...",
  "points": [
    {{"title": "...", "body": "..."}},
    {{"title": "...", "body": "..."}},
    {{"title": "...", "body": "..."}},
    {{"title": "...", "body": "..."}},
    {{"title": "...", "body": "..."}}
  ],
  "caption": "1-2 sentence post caption that drives saves/comments (no hashtags)",
  "hashtags": ["#lifeadvice", "...", "5-8 relevant hashtags"]
}}
```"""


def highlights_prompt(transcript: str, min_s: int, max_s: int, title: str = "") -> str:
    src = f' from "{title}"' if title else ""
    return f"""You are a viral short-form video editor for SYNERGIA (psychology, life advice, real experiences).

TASK: Below is a timestamped podcast transcript{src}. Find the 5 best self-contained moments
to cut into vertical Shorts/Reels/TikToks.

A great clip:
- is {min_s}-{max_s} seconds long (HARD LIMIT: strictly under 60 seconds),
- STARTS on a strong hook line (a bold claim, a question, a surprising story beat) — never mid-thought,
- ENDS on a complete thought / punchline,
- makes sense with zero context, and delivers psychology, life advice or a raw human experience.

Use timestamps exactly as they appear in the transcript (mm:ss or h:mm:ss).
Rank from best to worst.

Reply with ONE ```json code block and nothing else. Valid JSON only.

JSON SCHEMA:
```json
{{
  "clips": [
    {{
      "start": "mm:ss",
      "end": "mm:ss",
      "title": "short on-screen hook title, max 8 words",
      "why": "one sentence: why this will retain viewers",
      "caption": "1-2 sentence post caption (no hashtags)",
      "hashtags": ["#podcast", "...", "5-8 hashtags"]
    }}
  ]
}}
```

TRANSCRIPT:
{transcript}"""


def fix_prompt(errors: list[str], previous: str) -> str:
    errs = "\n".join(f"- {e}" for e in errors)
    return f"""Your previous reply could not be used. Problems:
{errs}

Fix ONLY these problems and reply again with ONE ```json code block (same schema, valid JSON, nothing else).

Previous reply:
{previous[:6000]}"""
