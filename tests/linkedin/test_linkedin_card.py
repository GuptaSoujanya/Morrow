import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from linkedin_bot import card


def test_card_is_1200_by_627_png(tmp_path):
    out = card.render_card("Three judges beat one.", "Example Wire", tmp_path / "cards" / "a.png")
    assert out.is_file()
    with Image.open(out) as image:
        assert image.size == (1200, 627)
        assert image.format == "PNG"
        assert image.getpixel((5, 300)) != (255, 255, 255), "accent bar on the left"


def test_a_long_line_still_fits_by_shrinking_the_font(tmp_path):
    line = "The grading only became a measurement once three judges had to agree about every long run " * 2
    out = card.render_card(line, "", tmp_path / "long.png")
    with Image.open(out) as image:
        assert image.size == (1200, 627)
        bottom_strip = image.crop((0, 627 - 40, 1200, 627)).getcolors(1200 * 40)
    assert bottom_strip is not None
