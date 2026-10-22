"""The post's visuals: a 1200x627 image card and a swipeable PDF carousel.

Drawn with Pillow only. The look is an engineering-blog one: a warm off-white
page with a faint blueprint grid, a white "editor window" panel, Avenir Next
for words and Menlo for labels, slate inks and a single indigo accent. The
carousel cover is the same system inverted on a near-black page.

Layout rules every page follows: text is placed by font metrics (anchors); a
text block always fits its box (the font shrinks, then the last line ends in
an ellipsis); lines are balanced so a paragraph never ends on a lone word;
rounded shapes are drawn on a 4x mask so their edges are smooth.
"""

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from PIL import Image, ImageDraw, ImageFilter, ImageFont

WIDTH, HEIGHT = 1200, 627
SLIDE_W, SLIDE_H = 1080, 1350

PAGE = "#F7F7F5"
SURFACE = "#FFFFFF"
GRID = "#ECECE8"
LINE = "#E2E8F0"
INK = "#0B1220"
BODY = "#334155"
MUTED = "#64748B"
DOTS = "#D4D4D8"
ACCENT = "#4F46E5"
ACCENT_SOFT = "#E0E7FF"
NIGHT = "#0B1220"
NIGHT_GRID = "#141C2E"
NIGHT_LINE = "#1E293B"
NIGHT_MUTED = "#94A3B8"
NIGHT_TEXT = "#CBD5E1"
NIGHT_ACCENT = "#A5B4FC"
WHITE = "#FFFFFF"

ELLIPSIS = "\u2026"
_SUPERSAMPLE = 4

Font = Union[ImageFont.FreeTypeFont, ImageFont.ImageFont]
Box = Tuple[int, int, int, int]

_AVENIR = "/System/Library/Fonts/Avenir Next.ttc"
_FALLBACK = {
    "bold": ("/System/Library/Fonts/Supplemental/Arial Bold.ttf",),
    "regular": ("/System/Library/Fonts/Supplemental/Arial.ttf",),
}
_MONO = (("/System/Library/Fonts/Menlo.ttc", 0, 1), ("/System/Library/Fonts/SFNSMono.ttf", 0, 0))
_AVENIR_STYLES = {"bold": ("Bold",), "regular": ("Regular",), "demi": ("Demi Bold",)}
_avenir_index = {}  # type: Dict[str, Optional[int]]


# --- fonts ----------------------------------------------------------------------


def _avenir(style: str) -> Optional[int]:
    if style in _avenir_index:
        return _avenir_index[style]
    found = None  # type: Optional[int]
    for index in range(16):
        try:
            face = ImageFont.truetype(_AVENIR, 12, index=index)
        except OSError:
            break
        if face.getname()[1] in _AVENIR_STYLES.get(style, ()):
            found = index
            break
    _avenir_index[style] = found
    return found


def _font(size: int, style: str = "regular") -> Font:
    index = _avenir(style)
    if index is not None:
        return ImageFont.truetype(_AVENIR, size, index=index)
    for path in _FALLBACK["regular" if style == "regular" else "bold"]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _mono(size: int, bold: bool = False) -> Font:
    for path, regular, heavy in _MONO:
        try:
            return ImageFont.truetype(path, size, index=heavy if bold else regular)
        except OSError:
            continue
    return _font(size, "demi" if bold else "regular")


def _metrics(font: Font) -> Tuple[int, int]:
    """(ascent, descent) in pixels; the bitmap default font has no metrics."""
    try:
        return font.getmetrics()  # type: ignore[union-attr]
    except AttributeError:
        return 11, 3


# --- text layout ----------------------------------------------------------------


def _break_word(draw: ImageDraw.ImageDraw, word: str, font: Font, width: int) -> List[str]:
    pieces = []  # type: List[str]
    current = ""
    for ch in word:
        if current and draw.textlength(current + ch, font=font) > width:
            pieces.append(current)
            current = ch
        else:
            current += ch
    if current:
        pieces.append(current)
    return pieces


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: Font, width: int) -> List[str]:
    """Greedy word wrap; a word wider than the line is split, never overflowed."""
    lines = []  # type: List[str]
    current = []  # type: List[str]
    for word in text.split():
        if draw.textlength(word, font=font) > width:
            if current:
                lines.append(" ".join(current))
                current = []
            pieces = _break_word(draw, word, font, width)
            lines.extend(pieces[:-1])
            current = [pieces[-1]]
            continue
        trial = " ".join(current + [word])
        if current and draw.textlength(trial, font=font) > width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def _balanced(draw: ImageDraw.ImageDraw, text: str, font: Font, width: int) -> List[str]:
    """Same line count as a greedy wrap, but the narrowest width that keeps it."""
    lines = _wrap(draw, text, font, width)
    if len(lines) < 2:
        return lines
    low, high = width // 2, width
    while high - low > 4:
        mid = (low + high) // 2
        if len(_wrap(draw, text, font, mid)) == len(lines):
            high = mid
        else:
            low = mid
    return _wrap(draw, text, font, high)


def _ellipsize(draw: ImageDraw.ImageDraw, line: str, font: Font, width: int) -> str:
    words = line.split()
    while words:
        trial = " ".join(words).rstrip(",;:.") + ELLIPSIS
        if draw.textlength(trial, font=font) <= width:
            return trial
        words.pop()
    return ELLIPSIS


def _clip(draw: ImageDraw.ImageDraw, text: str, font: Font, width: int) -> str:
    return text if draw.textlength(text, font=font) <= width else _ellipsize(draw, text, font, width)


class Block:
    """A fitted paragraph: font, lines and spacing, ready to draw."""

    def __init__(self, font: Font, lines: List[str], line_height: int) -> None:
        self.font = font
        self.lines = lines
        self.line_height = line_height
        self.ascent, self.descent = _metrics(font)

    @property
    def height(self) -> int:
        if not self.lines:
            return 0
        return (len(self.lines) - 1) * self.line_height + self.ascent + self.descent

    def draw(self, draw: ImageDraw.ImageDraw, x: int, y: int, fill: str) -> int:
        """Draw with the first line's ascender at y; returns the block's bottom."""
        for number, line in enumerate(self.lines):
            draw.text((x, y + number * self.line_height), line, font=self.font, fill=fill, anchor="la")
        return y + self.height


def _fit(
    draw: ImageDraw.ImageDraw, text: str, width: int, height: int,
    start: int, minimum: int, style: str, leading: float,
) -> Block:
    """Largest size from start down to minimum whose balanced wrap fits the box.

    At the minimum size the text is cut to the lines that fit and the last one
    ends in an ellipsis, so a block can never run into whatever sits below it.
    """
    size = start
    while True:
        font = _font(size, style)
        block = Block(font, _balanced(draw, text, font, width), int(size * leading))
        if block.height <= height:
            return block
        if size <= minimum:
            break
        size = max(minimum, size - 2)
    usable = max(1, (height - block.ascent - block.descent) // block.line_height + 1)
    lines = _wrap(draw, text, font, width)[:usable]
    lines[-1] = _ellipsize(draw, lines[-1], font, width)
    return Block(font, lines, block.line_height)


# --- surfaces and shapes --------------------------------------------------------


def _rgba(color: str, alpha: int = 255) -> Tuple[int, int, int, int]:
    color = color.lstrip("#")
    return (int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16), alpha)


def _page(size: Tuple[int, int], color: str, grid: str, step: int) -> Image.Image:
    """A flat page with a faint blueprint grid."""
    image = Image.new("RGBA", size, _rgba(color))
    draw = ImageDraw.Draw(image)
    for x in range(step, size[0], step):
        draw.line([x, 0, x, size[1]], fill=grid, width=1)
    for y in range(step, size[1], step):
        draw.line([0, y, size[0], y], fill=grid, width=1)
    return image


def _smooth(image: Image.Image, box: Box, color: str, radius: int, alpha: int = 255) -> None:
    """A rounded rectangle (a circle when radius is half the side) with clean edges."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    s = _SUPERSAMPLE
    mask = Image.new("L", (w * s, h * s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w * s - 1, h * s - 1], radius=radius * s, fill=alpha)
    mask = mask.resize((w, h), Image.LANCZOS)
    image.paste(Image.new("RGB", (w, h), _rgba(color)[:3]), (x0, y0), mask)


def _shadow(image: Image.Image, box: Box, radius: int, blur: int = 22, alpha: int = 30) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    ImageDraw.Draw(layer).rounded_rectangle([x0, y0 + blur // 2, x1, y1 + blur // 2], radius=radius,
                                            fill=(15, 23, 42, alpha))
    image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def _panel(image: Image.Image, box: Box, radius: int = 18, border: str = LINE, fill: str = SURFACE) -> None:
    """A white card with a hairline border and a soft drop shadow."""
    _shadow(image, box, radius)
    _smooth(image, box, border, radius)
    x0, y0, x1, y1 = box
    _smooth(image, (x0 + 1, y0 + 1, x1 - 1, y1 - 1), fill, radius - 1)


def _chrome(image: Image.Image, box: Box, title: str, height: int = 52) -> int:
    """Editor-window title bar along the top of a panel; returns its bottom edge."""
    x0, y0, x1, _ = box
    draw = ImageDraw.Draw(image)
    mid = y0 + height // 2
    for i in range(3):
        cx = x0 + 28 + i * 22
        _smooth(image, (cx - 6, mid - 6, cx + 6, mid + 6), DOTS, 6)
    font = _mono(16)
    draw.text((x0 + 28 + 3 * 22 + 12, mid), _clip(draw, title, font, x1 - x0 - 200), font=font,
              fill=MUTED, anchor="lm")
    draw.line([x0 + 1, y0 + height, x1 - 1, y0 + height], fill=LINE, width=1)
    return y0 + height


def _initials(author: str) -> str:
    return "".join(part[0] for part in author.split()[:2]).upper() or "?"


def _avatar(image: Image.Image, x: int, y: int, size: int, author: str,
            fill: str = ACCENT, ink: str = WHITE) -> None:
    _smooth(image, (x, y, x + size, y + size), fill, size // 2)
    ImageDraw.Draw(image).text((x + size / 2, y + size / 2), _initials(author),
                               font=_font(int(size * 0.38), "bold"), fill=ink, anchor="mm")


def _pill(image: Image.Image, x: int, y: int, text: str, size: int, fill: str, ink: str,
          mono: bool = True) -> int:
    """A rounded label with its text centred on the real glyph box; returns its right edge."""
    draw = ImageDraw.Draw(image)
    font = _mono(size, bold=True) if mono else _font(size, "demi")
    w = int(draw.textlength(text, font=font))
    pad_x, height = int(size * 0.9), int(size * 2.0)
    right = x + w + 2 * pad_x
    _smooth(image, (x, y, right, y + height), fill, height // 2)
    draw.text((x + pad_x + w / 2, y + height / 2), text, font=font, fill=ink, anchor="mm")
    return right


def _bar(image: Image.Image, x: int, y: int, width: int, thickness: int, color: str) -> None:
    _smooth(image, (x, y, x + width, y + thickness), color, thickness // 2)


def _slug(text: str) -> str:
    words = "".join(ch.lower() if ch.isalnum() else " " for ch in text).split()
    return "-".join(words[:4]) or "notes"


# --- the image card -------------------------------------------------------------


def render_card(
    card_line: str,
    source_name: str,
    out_path: Union[str, Path],
    author: str = "Soujanya Gupta",
    site: str = "soujanyalab.in",
    accent: str = ACCENT,
    tag: str = "NOTES ON AI ENGINEERING",
) -> Path:
    """Draw the card and return its path; parent directories are created."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    image = _page((WIDTH, HEIGHT), PAGE, GRID, 32)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 7, HEIGHT], fill=accent)

    box = (56, 44, WIDTH - 56, HEIGHT - 52)
    _panel(image, box)
    top = _chrome(image, box, "~/notes/%s.md" % _slug(tag))

    pad = 52
    left, right = box[0] + pad, box[2] - pad
    draw.text((left, top + 38), "// " + tag.lower(), font=_mono(18), fill=accent, anchor="la")

    footer = box[3] - 92
    head_top, head_bottom = top + 84, footer - 34
    block = _fit(draw, card_line, right - left, head_bottom - head_top - 30, 58, 32, "bold", 1.16)
    y = head_top + max(0, (head_bottom - head_top - 30 - block.height) // 2)
    end = block.draw(draw, left, y, INK)
    _bar(image, left, end + 22, 64, 6, accent)

    draw.line([left, footer, right, footer], fill=LINE, width=1)
    avatar, mid = 44, footer + 46
    _avatar(image, left, mid - avatar // 2, avatar, author, fill=accent)
    draw.text((left + avatar + 16, mid - 1), author, font=_font(22, "bold"), fill=INK, anchor="ls")
    draw.text((left + avatar + 16, mid + 5), site, font=_mono(15), fill=MUTED, anchor="lt")
    if source_name:
        small = _mono(15)
        draw.text((right, mid), _clip(draw, "via %s" % source_name, small, 420),
                  font=small, fill=MUTED, anchor="rm")

    image.convert("RGB").save(out, "PNG", optimize=True)
    return out


# --- the carousel ---------------------------------------------------------------

_M = 96
_FOOTER_Y = SLIDE_H - 128


def _slide_footer(image: Image.Image, index: int, total: int, author: str, dark: bool) -> None:
    full = SLIDE_W - 2 * _M
    _bar(image, _M, _FOOTER_Y, full, 6, NIGHT_LINE if dark else LINE)
    _bar(image, _M, _FOOTER_Y, max(6, int(full * (index + 1) / float(total))), 6,
         NIGHT_ACCENT if dark else ACCENT)
    draw = ImageDraw.Draw(image)
    ink = NIGHT_MUTED if dark else MUTED
    draw.text((_M, _FOOTER_Y + 50), author, font=_font(24, "demi"), fill=ink, anchor="lm")
    draw.text((SLIDE_W - _M, _FOOTER_Y + 50), "%02d / %02d" % (index + 1, total),
              font=_mono(22), fill=ink, anchor="rm")


def _arrow(image: Image.Image, x: int, y: int, fill: str, ink: str) -> None:
    """A right-pointing arrow in a circle: 'swipe'."""
    size = 88
    _smooth(image, (x, y, x + size, y + size), fill, size // 2)
    s = _SUPERSAMPLE
    mask = Image.new("L", (size * s, size * s), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([26 * s, 41 * s, 56 * s, 47 * s], radius=3 * s, fill=255)
    draw.polygon([(50 * s, 30 * s), (64 * s, 44 * s), (50 * s, 58 * s)], fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)
    image.paste(Image.new("RGB", (size, size), _rgba(ink)[:3]), (x, y), mask)


def _cover(title: str, subtitle: str, author: str, site: str, total: int) -> Image.Image:
    image = _page((SLIDE_W, SLIDE_H), NIGHT, NIGHT_GRID, 48)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 9, SLIDE_H], fill=ACCENT)
    draw.text((_M, 120), "~/notes/%s.md" % _slug(title), font=_mono(22), fill=NIGHT_MUTED, anchor="la")
    _pill(image, _M, 176, "SWIPE THROUGH", 20, NIGHT_LINE, NIGHT_ACCENT)

    profile_top = _FOOTER_Y - 170
    width = SLIDE_W - 2 * _M
    sub = _fit(draw, subtitle, width, 170, 36, 26, "regular", 1.4) if subtitle else None
    sub_space = (sub.height + 84) if sub else 0
    title_top = 300
    block = _fit(draw, title, width, profile_top - 70 - sub_space - title_top, 92, 50, "bold", 1.1)
    y = block.draw(draw, _M, title_top, WHITE)
    _bar(image, _M, y + 32, 120, 8, ACCENT)
    if sub:
        sub.draw(draw, _M, y + 84, NIGHT_TEXT)

    avatar = 80
    _avatar(image, _M, profile_top, avatar, author)
    mid = profile_top + avatar // 2
    draw.text((_M + avatar + 24, mid - 4), author, font=_font(32, "bold"), fill=WHITE, anchor="ls")
    draw.text((_M + avatar + 24, mid + 8), site, font=_mono(22), fill=NIGHT_MUTED, anchor="lt")
    _arrow(image, SLIDE_W - _M - 88, mid - 44, ACCENT, WHITE)
    _slide_footer(image, 0, total, author, dark=True)
    return image.convert("RGB")


def _content(number: int, title: str, body: str, author: str, index: int, total: int) -> Image.Image:
    image = _page((SLIDE_W, SLIDE_H), PAGE, GRID, 40)
    draw = ImageDraw.Draw(image)
    draw.text((SLIDE_W - _M + 8, 56), "%02d" % number, font=_font(240, "bold"), fill=ACCENT_SOFT, anchor="ra")

    box = (72, 250, SLIDE_W - 72, _FOOTER_Y - 56)
    _panel(image, box, radius=22)
    top = _chrome(image, box, "step-%02d.md" % number, height=60)
    pad = 56
    left, width = box[0] + pad, box[2] - box[0] - 2 * pad
    draw.text((left, top + 48), "STEP %02d" % number, font=_mono(22, bold=True), fill=ACCENT, anchor="la")

    title_block = _fit(draw, title, width, 260, 62, 40, "bold", 1.14)
    y = title_block.draw(draw, left, top + 100, INK)
    _bar(image, left, y + 34, 56, 6, ACCENT)
    body_top = y + 76
    body_block = _fit(draw, body, width, box[3] - pad - body_top, 38, 26, "regular", 1.55)
    body_block.draw(draw, left, body_top, BODY)
    _slide_footer(image, index, total, author, dark=False)
    return image.convert("RGB")


def _closing(question: str, author: str, site: str, index: int, total: int) -> Image.Image:
    image = _page((SLIDE_W, SLIDE_H), PAGE, GRID, 40)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 9, SLIDE_H], fill=ACCENT)
    _pill(image, _M, 150, "YOUR TURN", 20, ACCENT, WHITE)

    profile_top = _FOOTER_Y - 190
    box = (72, 260, SLIDE_W - 72, profile_top - 60)
    _panel(image, box, radius=22)
    top = _chrome(image, box, "comments.md", height=60)
    pad = 56
    left, width = box[0] + pad, box[2] - box[0] - 2 * pad
    prompt = "Tell me in the comments."
    block = _fit(draw, question, width, box[3] - pad - 90 - (top + 56), 70, 40, "bold", 1.16)
    y = block.draw(draw, left, top + 56, INK)
    draw.text((left, y + 44), prompt, font=_mono(26), fill=ACCENT, anchor="la")

    avatar = 88
    _avatar(image, _M, profile_top, avatar, author)
    mid = profile_top + avatar // 2
    text_x = _M + avatar + 26
    draw.text((text_x, mid - 6), "Follow %s" % author, font=_font(34, "bold"), fill=INK, anchor="ls")
    small = _mono(22)
    tagline = _clip(draw, "notes on AI agents and evals | %s" % site, small, SLIDE_W - _M - text_x)
    draw.text((text_x, mid + 8), tagline, font=small, fill=MUTED, anchor="lt")
    _slide_footer(image, index, total, author, dark=False)
    return image.convert("RGB")


def render_carousel(
    title: str,
    slides: Sequence[Dict[str, str]],
    question: str,
    out_path: Union[str, Path],
    subtitle: str = "",
    author: str = "Soujanya Gupta",
    site: str = "soujanyalab.in",
) -> Path:
    """A cover, one page per slide, and a closing question, saved as one PDF."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    total = len(slides) + 2
    pages = [_cover(title, subtitle, author, site, total)]
    for number, slide in enumerate(slides, start=1):
        pages.append(_content(number, slide["title"], slide["body"], author, number, total))
    pages.append(_closing(question, author, site, total - 1, total))
    pages[0].save(out, "PDF", save_all=True, append_images=pages[1:], resolution=144.0)
    return out
