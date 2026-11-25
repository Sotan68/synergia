"""Canvas geometry and safe-zone helpers."""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw

from synergia.config import CFG


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2

    def sub(self, top: float = 0, bottom: float = 1) -> "Box":
        """Vertical slice by fraction (0..1)."""
        y0 = self.y + int(self.h * top)
        y1 = self.y + int(self.h * bottom)
        return Box(self.x, y0, self.w, y1 - y0)


W, H = CFG.brand.width, CFG.brand.height
SZ = CFG.safe_zone
SAFE = Box(SZ.left, SZ.top, SZ.right - SZ.left, SZ.bottom - SZ.top)
# Centred layouts: the safe zone is lopsided (wider right margin for the app's buttons), so its own
# centre sits left of the screen's. This box keeps the larger margin on both sides, so anything
# centred in it is centred on screen and still inside the safe zone.
_M = max(SZ.left, W - SZ.right)
CENTRE = Box(_M, SZ.top, W - 2 * _M, SZ.bottom - SZ.top)
# Where content goes on D / E frames: the safe zone minus the footer row (wordmark) at its bottom.
BODY = Box(CENTRE.x, SZ.top, CENTRE.w, SZ.bottom - 80 - SZ.top)


def centred_top(height: int, area: Box = BODY) -> int:
    """Top y that centres a block of `height` px vertically in `area` (pinned to its top if too tall)."""
    return area.y + max(0, (area.h - height) // 2)


def safe_for(height: int) -> Box:
    """Safe box scaled for a non-9:16 canvas (e.g. 4:5 feed)."""
    if height == H:
        return SAFE
    margin_y = int(height * 0.08)
    return Box(SZ.left, margin_y, SZ.right - SZ.left, height - 2 * margin_y)


def draw_safe_zone(img: Image.Image) -> Image.Image:
    """Debug overlay: red rectangle for safe zone."""
    out = img.convert("RGBA")
    d = ImageDraw.Draw(out)
    box = safe_for(out.height)
    d.rectangle([box.x, box.y, box.right, box.bottom], outline=(255, 60, 60, 255), width=4)
    return out.convert("RGB")
