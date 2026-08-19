"""Generate the project icon and logo.

Kept in the repo so the artwork can be regenerated rather than being an opaque
binary. Run: python tools/make_logo.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent

# Home Assistant blue, on the near-black the HA dark theme uses.
BLUE = (3, 169, 244)
BLUE_DIM = (3, 169, 244, 90)
BG_TOP = (28, 34, 43)
BG_BOTTOM = (17, 21, 27)
# Lifted, so the plate still has an edge against a dark surface.
BG_TOP_DARK = (58, 69, 84)
BG_BOTTOM_DARK = (38, 46, 57)
WHITE = (255, 255, 255)

SS = 4  # supersample factor, for smooth curves without antialiasing tricks


def set_palette(palette: tuple[tuple[int, int, int], tuple[int, int, int]]) -> None:
    """Swap the plate colours between the light-theme and dark-theme variants."""
    global BG_TOP, BG_BOTTOM
    BG_TOP, BG_BOTTOM = palette


def _rounded_background(size: int) -> Image.Image:
    """Vertical gradient clipped to a squircle-ish rounded square."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gradient = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(gradient)
    for y in range(size):
        t = y / max(size - 1, 1)
        draw.line(
            [(0, y), (size, y)],
            fill=tuple(
                round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)
            )
            + (255,),
        )

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=255
    )
    img.paste(gradient, (0, 0), mask)
    return img


def _draw_remote(
    draw: ImageDraw.ImageDraw, size: int, cx: float | None = None, scale: float = 1.0
) -> None:
    """A remote, seen head on, in the lower half."""
    cx = size / 2 if cx is None else cx
    w = size * 0.30 * scale
    h = size * 0.46 * scale
    x0 = cx - w / 2
    y0 = size * 0.46 if scale == 1.0 else size * 0.50 - h * 0.10
    draw.rounded_rectangle(
        [x0, y0, x0 + w, y0 + h], radius=w * 0.30, fill=WHITE + (255,)
    )

    # The emitter, echoing the waves above it.
    r = w * 0.11
    cy = y0 + h * 0.17
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=BG_BOTTOM + (255,))

    # Two rows of buttons, deliberately sparse so it reads at 32px.
    br = w * 0.085
    for row in range(2):
        for col in (-1, 1):
            bx = cx + col * w * 0.22
            by = y0 + h * (0.45 + row * 0.24)
            draw.ellipse(
                [bx - br, by - br, bx + br, by + br], fill=BG_BOTTOM + (200,)
            )


def _draw_waves(
    draw: ImageDraw.ImageDraw, size: int, cx: float | None = None, scale: float = 1.0
) -> None:
    """Three arcs rising from the emitter: the signal going out."""
    cx = size / 2 if cx is None else cx
    cy = (size * 0.54) if scale == 1.0 else size * 0.56
    for radius_f, width_f, colour in [
        (0.20, 0.035, BLUE),
        (0.30, 0.033, BLUE),
        (0.40, 0.030, BLUE_DIM),
    ]:
        r = size * radius_f * scale
        draw.arc(
            [cx - r, cy - r, cx + r, cy + r],
            start=215,
            end=325,
            fill=colour if len(colour) == 4 else colour + (255,),
            width=max(int(size * width_f * scale), 1),
        )


def build(size: int) -> Image.Image:
    canvas = size * SS
    img = _rounded_background(canvas)
    draw = ImageDraw.Draw(img)
    _draw_waves(draw, canvas)
    _draw_remote(draw, canvas)
    return img.resize((size, size), Image.LANCZOS)


def _font(size: int):
    """Any bold sans will do; fall back rather than fail on a bare machine."""
    for path in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def build_logo(width: int = 640, height: int = 240) -> Image.Image:
    """Wide variant: icon and wordmark on the same dark plate.

    The plate is not decoration - a transparent logo with white text vanishes on
    light backgrounds, and dark text vanishes on the HA dark theme.
    """
    canvas_w, canvas_h = width * SS, height * SS
    img = _rounded_background(canvas_h)
    img = img.resize((canvas_h, canvas_h), Image.LANCZOS)

    plate = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    mask = Image.new("L", (canvas_w, canvas_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, canvas_w - 1, canvas_h - 1], radius=int(canvas_h * 0.22), fill=255
    )
    gradient = Image.new("RGBA", (canvas_w, canvas_h))
    gd = ImageDraw.Draw(gradient)
    for y in range(canvas_h):
        t = y / max(canvas_h - 1, 1)
        gd.line(
            [(0, y), (canvas_w, y)],
            fill=tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)) + (255,),
        )
    plate.paste(gradient, (0, 0), mask)

    draw = ImageDraw.Draw(plate)
    inset = canvas_h * 0.16
    _draw_waves(draw, canvas_h, cx=inset + canvas_h * 0.34, scale=0.68)
    _draw_remote(draw, canvas_h, cx=inset + canvas_h * 0.34, scale=0.68)

    text_x = inset + canvas_h * 0.72
    draw.text(
        (text_x, canvas_h * 0.30),
        "Broadlink",
        font=_font(int(canvas_h * 0.24)),
        fill=WHITE + (255,),
    )
    draw.text(
        (text_x, canvas_h * 0.55),
        "Commands",
        font=_font(int(canvas_h * 0.24)),
        fill=BLUE + (255,),
    )
    return plate.resize((width, height), Image.LANCZOS)


if __name__ == "__main__":
    brand = ROOT / "custom_components" / "broadlink_commands" / "brand"
    brand.mkdir(parents=True, exist_ok=True)

    # Home Assistant serves dark_* on dark themes; the light plate would
    # otherwise disappear against the dark surface behind it.
    variants = {"": (BG_TOP, BG_BOTTOM), "dark_": (BG_TOP_DARK, BG_BOTTOM_DARK)}

    for prefix, palette in variants.items():
        set_palette(palette)
        build(256).save(brand / f"{prefix}icon.png")
        build(512).save(brand / f"{prefix}icon@2x.png")
        build_logo(640, 240).save(brand / f"{prefix}logo.png")
        build_logo(1280, 480).save(brand / f"{prefix}logo@2x.png")

    # Repository-level copies, for the README and GitHub.
    set_palette(variants[""])
    build(256).save(ROOT / "icon.png")
    build_logo(640, 240).save(ROOT / "logo.png")

    print(f"wrote {len(list(brand.iterdir()))} brand images + README artwork")
