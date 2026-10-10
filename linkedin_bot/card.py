"""A plain 1200x627 image card: one line of the author's words, her name, the source."""

from pathlib import Path
from typing import List, Union

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1200, 627
BAR_WIDTH = 22
MARGIN = 80
TEXT_WIDTH = 1000
TEXT_HEIGHT = 400
START_SIZE = 60
MIN_SIZE = 34
STEP = 4
MUTED = "#6b7280"

FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Charter.ttc",
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: Union[ImageFont.FreeTypeFont, ImageFont.ImageFont], width: int) -> List[str]:
    lines = []  # type: List[str]
    current = []  # type: List[str]
    for word in text.split():
        trial = " ".join(current + [word])
        if current and draw.textlength(trial, font=font) > width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def render_card(
    card_line: str,
    source_name: str,
    out_path: Union[str, Path],
    author: str = "Soujanya Gupta",
    site: str = "soujanyalab.in",
    accent: str = "#1f4e79",
) -> Path:
    """Draw the card and return its path; parent directories are created."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, BAR_WIDTH, HEIGHT], fill=accent)

    size = START_SIZE
    while True:
        font = _font(size)
        lines = _wrap(draw, card_line, font, TEXT_WIDTH)
        line_height = int(size * 1.3)
        block_height = line_height * len(lines)
        if block_height <= TEXT_HEIGHT or size <= MIN_SIZE:
            break
        size -= STEP

    y = MARGIN
    for line in lines:
        draw.text((MARGIN, y), line, font=font, fill="#111111")
        y += line_height

    footer_font = _font(26)
    small_font = _font(20)
    baseline = HEIGHT - MARGIN + 10
    draw.text((MARGIN, baseline), author, font=footer_font, fill=accent)
    author_width = draw.textlength(author, font=footer_font)
    draw.text((MARGIN + author_width + 24, baseline + 4), site, font=small_font, fill=MUTED)
    if source_name:
        via = "via %s" % source_name
        via_width = draw.textlength(via, font=small_font)
        draw.text((WIDTH - MARGIN - via_width, baseline + 4), via, font=small_font, fill=MUTED)

    image.save(out, "PNG")
    return out
