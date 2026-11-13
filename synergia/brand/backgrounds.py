"""Procedural dark aesthetic backgrounds: gradient glow + vignette + film grain. No stock assets."""
from __future__ import annotations

import numpy as np
from PIL import Image

from synergia.config import CFG, hex_to_rgb


def make_background(seed: int, width: int | None = None, height: int | None = None,
                    variant: int = 0) -> Image.Image:
    """Return an RGB dark background.

    `seed` fixes the look for a whole post; `variant` nudges the glow position so a carousel
    feels cohesive but not identical.
    """
    b = CFG.brand
    w = width or b.width
    h = height or b.height
    rng = np.random.default_rng(seed)

    base = np.array(hex_to_rgb(b.background), dtype=np.float32)
    tint = np.array(hex_to_rgb(b.background_tints[rng.integers(len(b.background_tints))]),
                    dtype=np.float32)
    accent = np.array(hex_to_rgb(b.accent), dtype=np.float32)
    accent2 = np.array(hex_to_rgb(b.accent2), dtype=np.float32)

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    nx, ny = xx / w, yy / h

    # Soft glow, placed in the upper area and drifting with the variant.
    gx = 0.25 + 0.5 * rng.random() + 0.06 * np.sin(variant * 1.3)
    gy = 0.18 + 0.15 * rng.random() + 0.03 * np.cos(variant * 0.9)
    aspect = h / w
    d = np.sqrt((nx - gx) ** 2 + ((ny - gy) * aspect * 0.6) ** 2)
    glow = np.clip(1.0 - d / 0.95, 0, 1) ** 2.2

    # Gentle diagonal gradient.
    diag = np.clip((nx * 0.4 + ny * 0.6), 0, 1)

    img = base[None, None, :] * (1 - 0.35 * diag[..., None]) \
        + (tint - base)[None, None, :] * glow[..., None] * 1.4 \
        + accent[None, None, :] * (glow[..., None] ** 3) * 0.06

    # Secondary purple glow, opposite side and lower, for a blue -> purple blend.
    g2x, g2y = 1.0 - gx, min(0.9, gy + 0.55)
    d2 = np.sqrt((nx - g2x) ** 2 + ((ny - g2y) * aspect * 0.6) ** 2)
    glow2 = np.clip(1.0 - d2 / 0.85, 0, 1) ** 2.4
    img = img + accent2[None, None, :] * glow2[..., None] * 0.10

    # Vignette.
    if b.vignette > 0:
        vd = np.sqrt((nx - 0.5) ** 2 + ((ny - 0.5) * 0.9) ** 2) / 0.72
        vig = 1 - b.vignette * np.clip(vd, 0, 1) ** 2.5
        img *= vig[..., None]

    # Film grain (monochrome).
    if b.grain > 0:
        noise = rng.normal(0, 255 * b.grain, size=(h, w)).astype(np.float32)
        img += noise[..., None]

    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")
