"""Theme presets: the look a user picks in the setup wizard.

Each theme has its own fonts, colours and layout:
- [paper]  colours of the Engine A / B slides (background, ink, soft, accent, accent2, texture)
- [layout] Engine A / B layout: background kind, alignment, how **highlighted** words look,
           the section-header style
- [quiz]   Engine D / E card style and colours
- [fonts]  headline / text / paragraph / numeral fonts (A / B) and the quiz family (D / E)
- [brand]  logo-mark colours and the accents used for Engine C subtitles

A preset is applied between config.toml's defaults and the user's profile, so anything set
explicitly in the profile still wins. Pure data: synergia.config loads it.
"""
from __future__ import annotations


def _v(file: str, **axes) -> str:
    """Font path, with variable-font axes after "|"."""
    ax = ",".join(f"{k.replace('_', ' ')}={v}" for k, v in axes.items())
    return f"assets/fonts/{file}" + (f"|{ax}" if ax else "")


def _quiz_fonts(file: str, weights=(800, 700, 600, 500), **axes) -> dict:
    return {f"quiz_{r}": _v(file, Weight=w, **axes)
            for r, w in zip(("heavy", "bold", "semibold", "medium"), weights)}


THEMES: dict[str, dict] = {
    # ------------------------------------------------------------------ editorial paper
    "synergia": {
        "label": "Synergia", "blurb": "Editorial. Textured paper, elegant serif headlines, blue italic highlights.",
        "paper": {"background": "#F6F5FC", "ink": "#14143C", "soft": "#585C84", "accent": "#2F4BFF",
                  "accent2": "#7457F5", "grain": 0.026, "mottle": 0.016, "tint": 0.035},
        "layout": {"blueprint": "editorial", "bg": "paper", "align": "left", "highlight": "italic",
                   "header": "rule"},
        "quiz": {"style": "sheet", "surface": "#FFFFFF", "text": "#14143C", "muted": "#6A6E96",
                 "accent": "#2F4BFF", "accent2": "#7457F5", "cobalt": "#2A45F2", "cobalt2": "#4A2FD6"},
        "fonts": {"serif": _v("InstrumentSerif-Regular.ttf"), "serif_italic": _v("InstrumentSerif-Italic.ttf"),
                  "display_medium": _v("InterDisplay-Medium.ttf"),
                  "display_semibold": _v("InterDisplay-SemiBold.ttf"),
                  "paragraph": _v("Newsreader.ttf", Weight=480, Optical_Size=36),
                  "numeral": _v("InstrumentSerif-Italic.ttf"),
                  **_quiz_fonts("BricolageGrotesque.ttf", Optical_Size=48)},
        "brand": {"mark_colors": ["#5B9CFF", "#A78BFA"], "accent": "#6FA8FF", "accent2": "#A78BFA"},
    },
    # ------------------------------------------------------------------ graph-paper notes
    "notebook": {
        "label": "Notebook", "blurb": "Notebook page. Ruled lines, a red margin, sticky notes and highlighter.",
        "paper": {"background": "#FBFBF6", "ink": "#1B1F3B", "soft": "#5A6080", "accent": "#2563EB",
                  "accent2": "#2563EB", "grain": 0.018, "mottle": 0.008, "tint": 0.0},
        "layout": {"blueprint": "notebook", "bg": "notebook", "align": "left", "highlight": "marker",
                   "marker": "#FFE27A", "header": "pill"},
        "quiz": {"style": "grid", "surface": "#FFFFFF", "text": "#1B1F3B", "muted": "#5A6080",
                 "accent": "#2563EB", "accent2": "#E8A10C"},
        "fonts": {"serif": _v("SpaceGrotesk.ttf", Weight=700), "serif_italic": _v("SpaceGrotesk.ttf", Weight=700),
                  "display_medium": _v("SpaceGrotesk.ttf", Weight=500),
                  "display_semibold": _v("SpaceGrotesk.ttf", Weight=600),
                  "paragraph": _v("SpaceGrotesk.ttf", Weight=500), "numeral": _v("SpaceGrotesk.ttf", Weight=700),
                  **_quiz_fonts("SpaceGrotesk.ttf", (700, 700, 600, 500))},
        "brand": {"mark_colors": ["#2563EB", "#E8A10C"], "accent": "#5B8CFF", "accent2": "#F2B53A"},
    },
    # ------------------------------------------------------------------ bold colour block
    "cobalt": {
        "label": "Cobalt", "blurb": "Poster. A big blue block with giant headlines, lavender highlighter.",
        "paper": {"background": "#F3F4FB", "ink": "#14143C", "soft": "#565B85", "accent": "#2A45F2",
                  "accent2": "#2A45F2", "grain": 0.012, "mottle": 0.0, "tint": 0.0},
        "layout": {"blueprint": "poster", "bg": "flat", "align": "left", "highlight": "marker",
                   "marker": "#CFC4FF", "marker_ink": "#1B1670", "header": "pill",
                   "block": "#2A45F2", "block2": "#4A2FD6", "on_block": "#FFFFFF",
                   "block_accent": "#CFC4FF"},
        "quiz": {"style": "cobalt", "surface": "#FFFFFF", "text": "#14143C", "muted": "#6A6E96",
                 "accent": "#2F4BFF", "accent2": "#7457F5", "cobalt": "#2A45F2", "cobalt2": "#4A2FD6"},
        "fonts": {"serif": _v("BricolageGrotesque.ttf", Weight=800, Optical_Size=96),  # cobalt
                  "serif_italic": _v("BricolageGrotesque.ttf", Weight=800, Optical_Size=96),
                  "display_medium": _v("BricolageGrotesque.ttf", Weight=500, Optical_Size=36),
                  "display_semibold": _v("BricolageGrotesque.ttf", Weight=700, Optical_Size=36),
                  "paragraph": _v("BricolageGrotesque.ttf", Weight=600, Optical_Size=36),
                  "numeral": _v("BricolageGrotesque.ttf", Weight=800, Optical_Size=96),
                  **_quiz_fonts("BricolageGrotesque.ttf", Optical_Size=48)},
        "brand": {"mark_colors": ["#2A45F2", "#8C7CF0"], "accent": "#7D93FF", "accent2": "#CFC4FF"},
    },
    # ------------------------------------------------------------------ dark, warm serif
    "midnight": {
        "label": "Midnight", "blurb": "Cinematic. Deep navy in a thin gold frame, a huge faint number, titles low on screen.",
        "paper": {"background": "#0F1226", "ink": "#F4EFE6", "soft": "#ABA8BC", "accent": "#F2C14E",
                  "accent2": "#F2C14E", "grain": 0.012, "mottle": 0.0, "tint": 0.0},
        "layout": {"blueprint": "cinematic", "bg": "flat", "align": "left", "highlight": "color",
                   "header": "plain"},
        "quiz": {"style": "sheet", "surface": "#1A1E3D", "text": "#F4EFE6", "muted": "#ABA8BC",
                 "accent": "#F2C14E", "accent2": "#E58F65"},
        "fonts": {"serif": _v("Fraunces.ttf", Weight=500, Optical_Size=144, Softness=100),
                  "serif_italic": _v("Fraunces.ttf", Weight=500, Optical_Size=144, Softness=100),
                  "display_medium": _v("DMSans.ttf", Weight=500, Optical_Size=24),
                  "display_semibold": _v("DMSans.ttf", Weight=600, Optical_Size=24),
                  "paragraph": _v("Fraunces.ttf", Weight=400, Optical_Size=36, Softness=50),
                  "numeral": _v("Fraunces.ttf", Weight=300, Optical_Size=144, Softness=100),
                  **_quiz_fonts("DMSans.ttf", (800, 700, 600, 500), Optical_Size=32)},
        "brand": {"mark_colors": ["#F2C14E", "#E58F65"], "accent": "#F2C14E", "accent2": "#E58F65"},
    },
    # ------------------------------------------------------------------ warm gradient
    "sunset": {
        "label": "Sunset", "blurb": "Cards. Content on a floating card with a coral sticker, warm peach glow.",
        "paper": {"background": "#FFF4E6", "background2": "#FFD6C2", "ink": "#3A1F14", "soft": "#7E5A4A",
                  "accent": "#E4572E", "accent2": "#E4572E", "grain": 0.014, "mottle": 0.0, "tint": 0.0},
        "layout": {"blueprint": "cards", "bg": "gradient", "align": "center", "highlight": "italic",
                   "header": "rule", "card": "#FFFFFF", "sticker": "#E4572E"},
        "quiz": {"style": "sheet", "surface": "#FFFFFF", "text": "#3A1F14", "muted": "#7E5A4A",
                 "accent": "#E4572E", "accent2": "#F29E38"},
        "fonts": {"serif": _v("DMSerifDisplay-Regular.ttf"), "serif_italic": _v("DMSerifDisplay-Italic.ttf"),
                  "display_medium": _v("DMSans.ttf", Weight=500, Optical_Size=24),
                  "display_semibold": _v("DMSans.ttf", Weight=600, Optical_Size=24),
                  "paragraph": _v("DMSans.ttf", Weight=500, Optical_Size=24),
                  "numeral": _v("DMSerifDisplay-Italic.ttf"),
                  **_quiz_fonts("DMSans.ttf", (800, 700, 600, 500), Optical_Size=32)},
        "brand": {"mark_colors": ["#E4572E", "#F29E38"], "accent": "#FF7A50", "accent2": "#F29E38"},
    },
    # ------------------------------------------------------------------ stark minimal
    "minimal": {
        "label": "Minimal", "blurb": "Swiss grid. Giant numbers, a red bar, huge type anchored to the corners.",
        "paper": {"background": "#FFFFFF", "ink": "#111111", "soft": "#5E5E5E", "accent": "#FF3B30",
                  "accent2": "#FF3B30", "grain": 0.0, "mottle": 0.0, "tint": 0.0},
        "layout": {"blueprint": "swiss", "bg": "flat", "align": "left", "highlight": "underline",
                   "header": "plain"},
        "quiz": {"style": "plain", "surface": "#FFFFFF", "text": "#111111", "muted": "#6B6B6B",
                 "accent": "#FF3B30", "accent2": "#FF3B30"},
        "fonts": {"serif": _v("Inter-Black.ttf"), "serif_italic": _v("Inter-Black.ttf"),
                  "display_medium": _v("InterDisplay-Medium.ttf"),
                  "display_semibold": _v("InterDisplay-SemiBold.ttf"),
                  "paragraph": _v("InterDisplay-SemiBold.ttf"), "numeral": _v("Inter-Black.ttf"),
                  "quiz_heavy": _v("Inter-Black.ttf"), "quiz_bold": _v("Inter-Bold.ttf"),
                  "quiz_semibold": _v("Inter-SemiBold.ttf"), "quiz_medium": _v("Inter-Medium.ttf")},
        "brand": {"mark_colors": ["#111111", "#FF3B30"], "accent": "#FF5A4F", "accent2": "#FF8A80"},
    },
}
DEFAULT = "synergia"
ALIASES = {"grid": "notebook", "forest": "synergia", "rose": "sunset"}   # names used before


def expand(name: str) -> dict:
    """Config sections for a preset (unknown names fall back to the default)."""
    t = THEMES.get(ALIASES.get(name, name)) or THEMES[DEFAULT]
    return {k: v for k, v in t.items() if k not in ("label", "blurb")}
