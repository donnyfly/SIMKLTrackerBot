"""Minimal animated level-up cards for Discord notifications.

The renderer is deliberately self-contained: no remote assets, fonts, or image hosts.
It returns an in-memory GIF that discord.py can attach directly to a message.
"""

from __future__ import annotations

from io import BytesIO
import math

from PIL import Image, ImageDraw, ImageFont


WIDTH = 720
HEIGHT = 280
FRAMES = 18
DURATION_MS = 55

_BG = (12, 14, 20)
_PANEL = (18, 21, 30)
_TEXT = (241, 243, 248)
_MUTED = (145, 151, 166)
_ACCENT = (121, 134, 255)
_ACCENT_SOFT = (83, 92, 180)
_LINE = (42, 47, 61)


def _font(size: int):
    # Pillow's bundled default font keeps the Docker image self-contained.
    # Recent Pillow versions support scalable load_default(size=...).
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _ease_out_cubic(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return 1.0 - (1.0 - value) ** 3


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], amount: float):
    amount = max(0.0, min(1.0, amount))
    return tuple(round(x + (y - x) * amount) for x, y in zip(a, b))


def render_level_up_gif(
    level: int,
    rank: str,
    *,
    previous_level: int | None = None,
    previous_rank: str | None = None,
) -> BytesIO:
    """Render a compact animated GIF for a level-up notification."""

    level = max(1, int(level))
    previous_level = max(1, int(previous_level or max(1, level - 1)))
    rank = str(rank or "Newcomer")
    rank_up = bool(previous_rank and previous_rank != rank)

    frames: list[Image.Image] = []
    title_font = _font(18)
    level_font = _font(78)
    rank_font = _font(26)
    small_font = _font(15)

    for index in range(FRAMES):
        t = index / max(FRAMES - 1, 1)
        reveal = _ease_out_cubic(min(1.0, t / 0.58))
        pulse = (math.sin(t * math.pi) ** 2)

        image = Image.new("RGB", (WIDTH, HEIGHT), _BG)
        draw = ImageDraw.Draw(image)

        # Quiet panel with a thin animated signal line.
        draw.rounded_rectangle((22, 22, WIDTH - 22, HEIGHT - 22), radius=24, fill=_PANEL, outline=_LINE, width=1)
        line_end = 48 + int((WIDTH - 96) * reveal)
        draw.rounded_rectangle((48, HEIGHT - 49, line_end, HEIGHT - 45), radius=2, fill=_ACCENT)

        # Minimal concentric pulse around the level marker.
        cx, cy = 132, 137
        for ring in range(3):
            phase = max(0.0, min(1.0, t * 1.35 - ring * 0.12))
            radius = 34 + int(phase * 54)
            fade = max(0.0, 1.0 - phase)
            ring_color = _mix(_PANEL, _ACCENT_SOFT, fade * 0.75)
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=ring_color, width=2)

        core_radius = 27 + int(4 * pulse)
        draw.ellipse((cx - core_radius, cy - core_radius, cx + core_radius, cy + core_radius), fill=_mix(_ACCENT_SOFT, _ACCENT, 0.45 + pulse * 0.4))
        draw.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), fill=_TEXT)

        # Typography enters without visual clutter.
        x = 230
        title = "RANK UP" if rank_up else "LEVEL UP"
        draw.text((x, 58), title, font=title_font, fill=_ACCENT)

        displayed_level = previous_level if t < 0.18 else level
        level_color = _mix(_MUTED, _TEXT, reveal)
        draw.text((x, 82), str(displayed_level), font=level_font, fill=level_color)

        rank_y = 180
        draw.text((x + 4, rank_y), rank, font=rank_font, fill=_TEXT)
        if rank_up:
            draw.text((x + 4, rank_y + 38), "NEW RANK", font=small_font, fill=_ACCENT)
        else:
            draw.text((x + 4, rank_y + 38), "SIMKL TRACKER", font=small_font, fill=_MUTED)

        frames.append(image)

    output = BytesIO()
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=DURATION_MS,
        loop=0,
        optimize=True,
        disposal=2,
    )
    output.seek(0)
    return output
