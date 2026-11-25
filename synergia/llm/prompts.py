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


def highlights_prompt(transcript: str, min_s: int, max_s: int, title: str = "", n: int = 5) -> str:
    src = f' from "{title}"' if title else ""
    return f"""You are a viral short-form video editor for SYNERGIA (psychology, life advice, real experiences).

TASK: Below is a timestamped podcast transcript{src}. Find the {n} best self-contained moments
to cut into vertical Shorts/Reels/TikToks.

A great clip:
- is {min_s}-{max_s} seconds long (HARD LIMIT: strictly under 60 seconds),
- STARTS on a strong hook line (a bold claim, a question, a surprising story beat) — never mid-thought,
- ENDS on a complete thought / punchline,
- makes sense with zero context, and delivers psychology, life advice or a raw human experience.
Clips must not overlap each other.

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


SELF_ID_RULES = """Register: entertainment and self-recognition, not diagnosis. Relatable, specific, a little
uncomfortably accurate. Never medical or clinical claims, never labels like disorders, never
anything that could shame someone. Concrete everyday details beat abstract traits.

Sound like a real person posting, not like an AI or an ad:
- plain everyday words; no buzzwords like "reveals", "hidden", "unlock", "truly", "energy", "vibe"
- no dramatic two-part fragments ("Pick one. It says everything.", "Be honest.")
- no em dashes, no semicolons, no trailing full stop on cover_title"""


def checklist_prompt(topic: str, n: int) -> str:
    return f"""{BRAND_VOICE}

TASK: Write a "How many apply to you?" checklist video about: "{topic}"
Viewers count how many of the signs fit them and comment their score.

{SELF_ID_RULES}

Rules:
- cover_title: starts with the number {n}, max 12 words, e.g. "{n} signs you **overthink** everything".
- signs: exactly {n} items, each max 9 words, written in second person as a habit or moment
  ("You rehearse phone calls before making them"). No numbering, no ending period needed.
- Order them from most common to most specific, so the last ones feel like "how did they know".

{JSON_RULES}

JSON SCHEMA:
```json
{{
  "title": "post title for TikTok / Reels / Shorts: max 70 characters, curiosity hook, no hashtags, no emojis, no asterisks",
  "cover_title": "...",
  "signs": ["...", "..."],
  "caption": "1 sentence that asks for their score in the comments (no hashtags)",
  "hashtags": ["#psychology", "...", "5-8 relevant hashtags"]
}}
```"""


def pick_prompt(topic: str, n: int) -> str:
    return f"""{BRAND_VOICE}

TASK: Write a "Pick one" reveal video about: "{topic}"
The viewer sees {n} options, picks one, then each option reveals what it says about them.

{SELF_ID_RULES}

Rules:
- style: how the options look. One of "numbers", "colours", "shapes", "doors" - pick what fits the topic best.
  For "colours" give every option a "color" (hex like "#4F8CFF", clearly different from each other, readable on a dark background).
  For "shapes" give every option a "shape": one of circle, triangle, square, star, hexagon, diamond (all different).
- cover_title: the setup in one plain sentence, max 12 words, e.g. "Pick a **door** and see what it says about you"
- options: exactly {n}. "label" max 3 words (e.g. "Door 1", "Ocean blue", "The triangle").
  "trait" max 25 words: what picking it says about them - flattering but specific, so people share it.

{JSON_RULES}

JSON SCHEMA:
```json
{{
  "title": "post title for TikTok / Reels / Shorts: max 70 characters, curiosity hook, no hashtags, no emojis, no asterisks",
  "cover_title": "...",
  "style": "numbers",
  "options": [
    {{"label": "...", "trait": "...", "color": "#hex (colours only)", "shape": "(shapes only)"}}
  ],
  "caption": "1 sentence that asks which one they picked (no hashtags)",
  "hashtags": ["#personalitytest", "...", "5-8 relevant hashtags"]
}}
```"""


def topics_prompt(mode: str, past: list[str]) -> str:
    kind = ('"How many apply to you?" checklists (e.g. "signs you\'re a high-functioning overthinker")'
            if mode == "checklist" else
            '"Pick one" personality reveals (e.g. "pick a door to reveal your hidden strength")')
    avoid = "\n".join(f"- {t}" for t in past[:40]) or "- (none yet)"
    return f"""{BRAND_VOICE}

TASK: Suggest 10 fresh topics for {kind}.
Topics should be about psychology, relationships, habits, work, friendship, self-image - things
people instantly recognise themselves in and want to comment on. Mix light and deep.
{SELF_ID_RULES}

Do NOT repeat or closely paraphrase these topics already used:
{avoid}

Reply with ONE ```json code block and nothing else. Valid JSON only.
```json
{{"topics": ["...", "... 10 short topics, max 10 words each"]}}
```"""


IDEA_KINDS = {
    "concepts": ('psychology concepts for 10-second explainers: named effects, biases, laws or '
                 'phenomena (e.g. "The Spotlight Effect", "The Zeigarnik Effect")',
                 "Use the concept's real, searchable name. Max 6 words each."),
    "hooks": ('hooks for 5-point life-advice carousels (e.g. "5 things people regret not doing '
              'after 25", "5 signs someone truly respects you")',
              "Each hook names its 5 points and promises a specific payoff. Max 12 words each."),
}


def ideas_prompt(kind: str, n: int, past: list[str]) -> str:
    """Fresh topics for Engine A ("concepts") or Engine B ("hooks"), avoiding past ones."""
    what, rule = IDEA_KINDS[kind]
    avoid = "\n".join(f"- {t}" for t in past[:60]) or "- (none yet)"
    return f"""{BRAND_VOICE}

TASK: Suggest {n} fresh {what}.
Pick ones that make people stop scrolling, recognise themselves and comment. Mix light and deep.
{rule}

Do NOT repeat or closely paraphrase these, already used:
{avoid}

Reply with ONE ```json code block and nothing else. Valid JSON only.
```json
{{"topics": ["...", "... exactly {n} items"]}}
```"""
