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


SLIDES = [{"title": "Slide %d makes one point" % i, "body": "A short body for slide %d that explains it plainly." % i} for i in range(1, 6)]


def test_carousel_is_one_pdf_with_cover_slides_and_question(tmp_path):
    out = card.render_carousel("Why one judge is not enough", SLIDES, "How do you grade agent runs?",
                               tmp_path / "c" / "deck.pdf", subtitle="Notes from an eval platform")
    data = out.read_bytes()
    assert data[:5] == b"%PDF-"
    assert data.count(b"/Type /Page\n") == len(SLIDES) + 2


def _measure():
    from PIL import ImageDraw
    return ImageDraw.Draw(Image.new("RGB", (10, 10)))


def test_text_that_cannot_fit_is_cut_with_an_ellipsis_not_overflowed():
    draw = _measure()
    block = card._fit(draw, "word " * 400, 600, 200, 60, 30, "bold", 1.2)
    assert block.height <= 200
    assert block.lines[-1].endswith(card.ELLIPSIS)


def test_a_word_wider_than_the_line_is_split():
    draw = _measure()
    font = card._font(40, "bold")
    lines = card._wrap(draw, "x" * 200 + " tail", font, 300)
    assert all(draw.textlength(line, font=font) <= 300 for line in lines)
    assert "".join(lines).replace(" ", "").startswith("x" * 200)


def test_balanced_wrap_keeps_the_line_count_and_avoids_a_lone_last_word():
    draw = _measure()
    font = card._font(40, "bold")
    text = "Agent evals only became a measurement once the judges agreed"
    greedy = card._wrap(draw, text, font, 700)
    balanced = card._balanced(draw, text, font, 700)
    assert len(balanced) == len(greedy)
    assert len(balanced[-1].split()) > 1
