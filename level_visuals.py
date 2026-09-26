"""Minimal animated progression cards for Discord notifications.

The renderer is deliberately self-contained: no remote assets, fonts, or image hosts.
It returns an in-memory GIF that discord.py can attach directly to a message.
"""

from __future__ import annotations

from io import BytesIO
import colorsys
import math

from PIL import Image, ImageDraw, ImageFont
from progression import RANKS, rank_for_level


WIDTH = 720
HEIGHT = 280
FRAMES = 32
DURATION_MS = 70

_BG = (12, 14, 20)
_PANEL = (18, 21, 30)
_TEXT = (241, 243, 248)
_MUTED = (145, 151, 166)
_LINE = (42, 47, 61)

# One accent for each rank, ordered by the progression table. Keep the
# palette separate from the XP rules so all levels in a rank share a color.
_RANK_COLORS = (
    (139, 152, 170),  # Newcomer — slate
    (121, 159, 195),  # Casual Watcher — steel blue
    (104, 174, 215),  # Regular Viewer — azure
    (88, 196, 199),   # Binge Watcher — teal
    (107, 197, 160),  # Dedicated Viewer — jade
    (115, 167, 232),  # Media Enthusiast — sapphire
    (154, 140, 232),  # Watch Veteran — amethyst
    (192, 148, 232),  # Watch Master — violet
    (229, 182, 116),  # Watch Legend — champagne gold
    (245, 216, 142),  # Screen Immortal — radiant gold
)
_RANK_ACCENTS = {name: color for (_, name), color in zip(RANKS, _RANK_COLORS)}

# Prestiges begin beyond the rank palette: pale, luminous finishes rather
# than another saturated rainbow. Later cycles vary their hue while retaining
# the premium finish and the numbered emblem.
_PRESTIGE_FINISHES = (
    (226, 233, 244),  # 1 — moon silver
    (188, 228, 242),  # 2 — opal blue
    (220, 196, 244),  # 3 — royal amethyst
    (175, 235, 221),  # 4 — aurora jade
    (242, 199, 190),  # 5 — rose gold
    (249, 228, 175),  # 6 — celestial gold
)


def accent_for_level(level: int) -> tuple[int, int, int]:
    """Return the shared accent of the rank containing this level."""
    return _RANK_ACCENTS[rank_for_level(level)]


def prestige_style(prestige: int) -> tuple[tuple[int, int, int], int]:
    """A luminous finish and numbered emblem for each prestige."""
    prestige = max(1, int(prestige))
    index = (prestige - 1) % len(_PRESTIGE_FINISHES)
    cycle = (prestige - 1) // len(_PRESTIGE_FINISHES)
    base = _PRESTIGE_FINISHES[index]
    if not cycle:
        return base, index
    hue, saturation, _ = colorsys.rgb_to_hsv(*(channel / 255 for channel in base))
    hue = (hue + cycle * 0.61803398875) % 1.0
    rgb = colorsys.hsv_to_rgb(hue, saturation, 0.97)
    return tuple(round(channel * 255) for channel in rgb), index


def _prestige_emblem(draw: ImageDraw.ImageDraw, cx: int, cy: int, style: int):
    """Six crisp geometric insignias that survive GIF palette conversion."""
    ink=(25, 30, 43)
    if style == 0:  # crown
        draw.polygon(((cx - 18, cy - 8), (cx - 10, cy + 4), (cx, cy - 8), (cx + 10, cy + 4), (cx + 18, cy - 8), (cx + 15, cy + 13), (cx - 15, cy + 13)), fill=ink)
        draw.rectangle((cx - 15, cy + 15, cx + 15, cy + 19), fill=ink)
    elif style == 1:  # star
        points=[]
        for i in range(10):
            angle=-math.pi / 2 + i * math.pi / 5
            radius=19 if i % 2 == 0 else 8
            points.append((cx + round(math.cos(angle) * radius), cy + round(math.sin(angle) * radius)))
        draw.polygon(points, fill=ink)
    elif style == 2:  # diamond
        draw.polygon(((cx, cy - 19), (cx + 18, cy), (cx, cy + 19), (cx - 18, cy)), fill=ink)
        draw.line(((cx - 18, cy), (cx + 18, cy)), fill=_TEXT, width=2)
    elif style == 3:  # orbit
        draw.ellipse((cx - 15, cy - 15, cx + 15, cy + 15), outline=ink, width=4)
        draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=ink)
        draw.ellipse((cx + 12, cy - 17, cx + 20, cy - 9), fill=ink)
    elif style == 4:  # shield
        draw.polygon(((cx, cy - 19), (cx + 17, cy - 11), (cx + 13, cy + 10), (cx, cy + 20), (cx - 13, cy + 10), (cx - 17, cy - 11)), fill=ink)
        draw.line(((cx, cy - 11), (cx, cy + 11)), fill=_TEXT, width=3)
    else:  # sun
        draw.ellipse((cx - 10, cy - 10, cx + 10, cy + 10), fill=ink)
        for i in range(8):
            angle=i * math.pi / 4
            draw.line(((cx + round(math.cos(angle) * 15), cy + round(math.sin(angle) * 15)), (cx + round(math.cos(angle) * 21), cy + round(math.sin(angle) * 21))), fill=ink, width=3)


def render_prestige_gif(prestige: int) -> BytesIO:
    prestige=max(1, int(prestige))
    accent, emblem=prestige_style(prestige)
    soft=_mix(_PANEL, accent, 0.55)
    frames=[]
    for index in range(FRAMES):
        t=index / (FRAMES - 1)
        reveal=_ease_out_cubic(t / 0.72)
        pulse=math.sin(t * math.pi) ** 2
        image=Image.new("RGB", (WIDTH, HEIGHT), _BG)
        draw=ImageDraw.Draw(image)
        border=_mix(_LINE,accent,0.35)
        draw.rounded_rectangle((22, 22, WIDTH - 22, HEIGHT - 22), radius=24, fill=_PANEL, outline=border,width=2)
        # A restrained highlight differentiates prestige from regular ranks.
        draw.line((WIDTH-169,36,WIDTH-74,36),fill=_mix(_PANEL,accent,0.25),width=2)
        draw.rounded_rectangle((48, HEIGHT - 35, 48 + int((WIDTH - 96) * reveal), HEIGHT - 31), radius=2, fill=accent)
        cx,cy=132,137
        for ring in range(3):
            phase=max(0.0, min(1.0, t * 1.35 - ring * 0.12))
            radius=44 + int(phase * 54)
            draw.ellipse((cx-radius,cy-radius,cx+radius,cy+radius), outline=_mix(_PANEL,soft,(1-phase)*0.8), width=2)
        radius=34 + int(4*pulse)
        draw.ellipse((cx-radius,cy-radius,cx+radius,cy+radius), fill=_mix(soft,accent,0.55 + pulse*0.4))
        _prestige_emblem(draw,cx,cy-6,emblem)
        tier_label=f"P{prestige}"
        tier_font=_font(11)
        tier_width=draw.textbbox((0,0),tier_label,font=tier_font)[2]
        draw.text((cx-tier_width/2,cy+17),tier_label,font=tier_font,fill=(25,30,43))
        draw.text((230,58),"PRESTIGE UNLOCKED",font=_font(18),fill=accent)
        draw.text((230,82),str(prestige),font=_font(78),fill=_mix(_MUTED,_TEXT,reveal))
        draw.text((234,180),"A NEW CHAPTER",font=_font(26),fill=_TEXT)
        draw.text((234,212),"LEVEL RESET TO 1",font=_font(15),fill=accent)
        frames.append(image)
    output=BytesIO()
    frames[0].save(output,format="GIF",save_all=True,append_images=frames[1:],duration=DURATION_MS,loop=0,optimize=True,disposal=2)
    output.seek(0)
    return output


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
    prestige: int = 0,
) -> BytesIO:
    """Render a compact animated GIF for a level-up notification."""

    level = max(1, int(level))
    previous_level = max(1, int(previous_level or max(1, level - 1)))
    rank = str(rank or "Newcomer")
    rank_up = bool(previous_rank and previous_rank != rank)
    prestige = max(0, int(prestige))
    previous_accent = accent_for_level(previous_level)
    next_accent = accent_for_level(level)
    prestige_accent, prestige_emblem = prestige_style(prestige) if prestige else (None, None)

    frames: list[Image.Image] = []
    title_font = _font(18)
    level_font = _font(78)
    rank_font = _font(26)
    small_font = _font(15)

    for index in range(FRAMES):
        t = index / max(FRAMES - 1, 1)
        reveal = _ease_out_cubic(min(1.0, t / 0.72))
        pulse = (math.sin(t * math.pi) ** 2)
        accent = _mix(previous_accent, next_accent, _ease_out_cubic((t - 0.14) / 0.55))
        accent_soft = _mix(_PANEL, accent, 0.55)

        image = Image.new("RGB", (WIDTH, HEIGHT), _BG)
        draw = ImageDraw.Draw(image)

        # Quiet panel with a thin animated signal line.
        border=_mix(_LINE,prestige_accent,0.35) if prestige_accent else _LINE
        draw.rounded_rectangle((22, 22, WIDTH - 22, HEIGHT - 22), radius=24, fill=_PANEL, outline=border, width=1)
        # Give the signal sweep its own footer lane so it never crosses labels.
        line_y = HEIGHT - 35
        line_end = 48 + int((WIDTH - 96) * reveal)
        draw.rounded_rectangle((48, line_y, line_end, line_y + 4), radius=2, fill=accent)

        # Minimal concentric pulse around the level marker.
        cx, cy = 132, 137
        for ring in range(3):
            phase = max(0.0, min(1.0, t * 1.35 - ring * 0.12))
            radius = 34 + int(phase * 54)
            fade = max(0.0, 1.0 - phase)
            ring_color = _mix(_PANEL, accent_soft, fade * 0.75)
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=ring_color, width=2)

        core_radius = 27 + int(4 * pulse)
        draw.ellipse((cx - core_radius, cy - core_radius, cx + core_radius, cy + core_radius), fill=_mix(accent_soft, accent, 0.45 + pulse * 0.4))
        draw.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), fill=_TEXT)

        # Typography enters without visual clutter.
        x = 230
        title = "RANK UP" if rank_up else "LEVEL UP"
        draw.text((x, 58), title, font=title_font, fill=accent)
        if prestige:
            badge=f"PRESTIGE {prestige}"
            width=draw.textbbox((0,0),badge,font=small_font)[2]
            badge_center=610
            draw.text((badge_center-width/2,60), badge, font=small_font, fill=prestige_accent)
            draw.ellipse((badge_center-29,113,badge_center+29,171),fill=_mix(_PANEL,prestige_accent,0.8))
            _prestige_emblem(draw,badge_center,142,prestige_emblem)

        displayed_level = previous_level if t < 0.18 else level
        level_color = _mix(_MUTED, _TEXT, reveal)
        draw.text((x, 82), str(displayed_level), font=level_font, fill=level_color)

        rank_y = 180
        draw.text((x + 4, rank_y), rank, font=rank_font, fill=_TEXT)
        if rank_up:
            draw.text((x + 4, rank_y + 32), "NEW RANK", font=small_font, fill=accent)
        else:
            draw.text((x + 4, rank_y + 32), "SIMKL TRACKER", font=small_font, fill=_MUTED)

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


def render_achievement_gif(name: str, xp: int) -> BytesIO:
    """Render an achievement card in the same visual language as level-ups."""
    name = str(name or "Achievement")
    xp = max(0, int(xp))
    gold = (239, 193, 104)
    gold_soft = (111, 80, 45)
    title_font = _font(18)
    name_size = 36
    while name_size > 20:
        name_font = _font(name_size)
        if ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), name, font=name_font)[2] <= WIDTH - 280:
            break
        name_size -= 2
    name_font = _font(name_size)
    xp_font = _font(26)
    small_font = _font(15)
    frames: list[Image.Image] = []

    for index in range(FRAMES):
        t = index / max(FRAMES - 1, 1)
        reveal = _ease_out_cubic(min(1.0, t / 0.72))
        pulse = math.sin(t * math.pi) ** 2
        image = Image.new("RGB", (WIDTH, HEIGHT), _BG)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((22, 22, WIDTH - 22, HEIGHT - 22), radius=24, fill=_PANEL, outline=_LINE, width=1)
        line_y = HEIGHT - 35
        line_end = 48 + int((WIDTH - 96) * reveal)
        draw.rounded_rectangle((48, line_y, line_end, line_y + 4), radius=2, fill=gold)

        cx, cy = 132, 137
        for ring in range(3):
            phase = max(0.0, min(1.0, t * 1.35 - ring * 0.12))
            radius = 34 + int(phase * 54)
            ring_color = _mix(_PANEL, gold_soft, max(0.0, 1.0 - phase) * 0.8)
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=ring_color, width=2)
        core_radius = 27 + int(4 * pulse)
        draw.ellipse((cx - core_radius, cy - core_radius, cx + core_radius, cy + core_radius), fill=_mix(gold_soft, gold, 0.55 + pulse * 0.4))
        # Draw a small trophy directly so the GIF does not depend on emoji fonts.
        draw.line(((cx - 12, cy - 8), (cx - 20, cy - 8), (cx - 19, cy + 1), (cx - 10, cy + 4)), fill=_TEXT, width=3, joint="curve")
        draw.line(((cx + 12, cy - 8), (cx + 20, cy - 8), (cx + 19, cy + 1), (cx + 10, cy + 4)), fill=_TEXT, width=3, joint="curve")
        draw.polygon(((cx - 13, cy - 12), (cx + 13, cy - 12), (cx + 10, cy + 2), (cx + 5, cy + 8), (cx - 5, cy + 8), (cx - 10, cy + 2)), fill=_TEXT)
        draw.rectangle((cx - 2, cy + 8, cx + 2, cy + 15), fill=_TEXT)
        draw.rounded_rectangle((cx - 12, cy + 15, cx + 12, cy + 19), radius=2, fill=_TEXT)

        x = 230
        draw.text((x, 58), "ACHIEVEMENT UNLOCKED", font=title_font, fill=gold)
        draw.text((x, 93), name, font=name_font, fill=_mix(_MUTED, _TEXT, reveal))
        draw.text((x + 4, 175), f"+{xp:,} XP", font=xp_font, fill=gold)
        draw.text((x + 4, 213), "SIMKL TRACKER", font=small_font, fill=_MUTED)
        frames.append(image)

    output = BytesIO()
    frames[0].save(
        output, format="GIF", save_all=True, append_images=frames[1:],
        duration=DURATION_MS, loop=0, optimize=True, disposal=2,
    )
    output.seek(0)
    return output
