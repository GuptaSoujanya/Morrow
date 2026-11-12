"""Channel art and reel covers carry the mascot, and a cover is built from its own reel."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ARTWORK = ROOT / "studio" / "reels" / "artwork.py"

pytestmark = pytest.mark.skipif(not ARTWORK.exists(), reason="the private studio folder is not checked out")


def _png(path: Path, width: int, height: int, colour: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"color=c={colour}:s={width}x{height}:d=1", "-frames:v", "1", str(path)], check=True)
    return path


@pytest.fixture
def artwork(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("studio_reels_artwork_test", ARTWORK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "HERE", tmp_path)
    monkeypatch.setattr(module, "HOME", tmp_path / "artwork-workspace")
    monkeypatch.setattr(module, "MASCOT", tmp_path / "mascot")
    _png(tmp_path / "mascot" / "cutout.png", 400, 500, "red")
    for percent in (3, 50, 90):
        _png(tmp_path / "out" / "a-plan" / "day-01" / f"snap-{percent}.png", 108, 192, "blue")
    plan = {"id": "a-plan", "style": "clay", "items": [
        {"day": 1, "title": "Why a set beats a list", "hook": "Your in check scans everything",
         "style": "clay", "on_screen_text": ["list: checks all", "set: checks one"]}]}
    (tmp_path / "plans").mkdir(parents=True, exist_ok=True)
    (tmp_path / "plans" / "a-plan.json").write_text(json.dumps(plan), encoding="utf-8")
    return module


def _spec(kind, elements, width, height):
    return {"version": 1, "kind": kind, "canvas": {"width": width, "height": height, "background": "#080D18"},
            "description": "d", "alt_text": "a", "elements": elements}


def test_the_mascot_is_offered_everywhere_and_frames_only_to_that_reels_cover(artwork):
    assert sorted(artwork.available_assets("banner")) == ["mascot"]
    assert sorted(artwork.available_assets("avatar")) == ["mascot"]
    assert sorted(artwork.available_assets("cover", "a-plan", 1)) == ["frame-3", "frame-50", "frame-90", "mascot"]
    assert sorted(artwork.available_assets("cover")) == ["mascot"]
    assert sorted(artwork.available_assets("banner", "a-plan", 1)) == ["mascot"]
    assert sorted(artwork.available_assets("cover", "a-plan", 7)) == ["mascot"]


def test_a_cover_prompt_carries_that_reels_own_words_and_frames(artwork):
    assets = artwork.available_assets("cover", "a-plan", 1)
    reel = artwork.reel_facts("a-plan", 1)
    assert reel["hook"] == "Your in check scans everything" and reel["style"] == "clay"
    text = artwork._prompt("cover", "make it bold", "", artwork.brand_context(), None, assets, reel)
    assert "Your in check scans everything" in text and "list: checks all" in text
    assert "frame-50" in text and "mascot" in text
    assert "The mascot MUST appear" in text
    assert "a real frame of the reel" in text
    assert "mascot MUST appear" in artwork._prompt("banner", "p", "", artwork.brand_context(), None,
                                                   artwork.available_assets("banner"), None)


def test_the_schema_only_lets_the_design_name_a_real_asset(artwork):
    assets = artwork.available_assets("cover", "a-plan", 1)
    schema = artwork.design_schema("cover", assets)
    picture = [b for b in schema["properties"]["elements"]["items"]["anyOf"]
               if b["properties"]["type"]["enum"] == ["image"]][0]
    assert sorted(picture["properties"]["asset"]["enum"]) == sorted(assets)
    plain = artwork.design_schema("cover", {})
    assert all(b["properties"]["type"]["enum"] != ["image"] for b in plain["properties"]["elements"]["items"]["anyOf"])


def test_a_design_may_not_reach_for_a_picture_it_was_not_given(artwork, tmp_path):
    folder = tmp_path / "artwork-workspace" / "versions" / "art-cover-x"
    folder.mkdir(parents=True)
    spec = _spec("cover", [{"type": "image", "asset": "frame-50", "x": 0, "y": 0,
                            "width": 1080, "height": 1920, "opacity": 1}], 1080, 1920)
    with pytest.raises(artwork.ArtworkError):
        artwork._materialise_assets(spec, folder, artwork.available_assets("cover"))
    for bad in ("../../../etc/passwd", "mascot/../x", "", "A" * 60):
        broken = _spec("cover", [{"type": "image", "asset": bad, "x": 0, "y": 0,
                                  "width": 1080, "height": 1920, "opacity": 1}], 1080, 1920)
        with pytest.raises(artwork.ArtworkError):
            artwork.validate_spec(broken, "cover")


def test_a_picture_must_be_at_least_partly_on_the_canvas(artwork):
    off = _spec("banner", [{"type": "image", "asset": "mascot", "x": 3000, "y": 0,
                            "width": 400, "height": 400, "opacity": 1}], 2560, 1440)
    with pytest.raises(artwork.ArtworkError):
        artwork.validate_spec(off, "banner")
    tiny = _spec("banner", [{"type": "image", "asset": "mascot", "x": 0, "y": 0,
                             "width": 10, "height": 400, "opacity": 1}], 2560, 1440)
    with pytest.raises(artwork.ArtworkError):
        artwork.validate_spec(tiny, "banner")


def test_rendering_paints_the_mascot_and_keeps_the_svg_self_contained(artwork, tmp_path):
    folder = tmp_path / "artwork-workspace" / "versions" / "art-cover-render"
    folder.mkdir(parents=True)
    spec = _spec("cover", [
        {"type": "image", "asset": "frame-50", "x": 0, "y": 0, "width": 1080, "height": 1200, "opacity": 0.5},
        {"type": "image", "asset": "mascot", "x": 600, "y": 1300, "width": 400, "height": 500, "opacity": 1}], 1080, 1920)
    used = artwork._materialise_assets(spec, folder, artwork.available_assets("cover", "a-plan", 1))
    assert used == ["frame-50", "mascot"]
    assert (folder / "asset-mascot.png").is_file() and (folder / "asset-frame-50.png").is_file()

    artwork.render(spec, folder)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(folder / "artwork.png"), "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    red = sum(1 for i in range(0, len(raw) - 2, 3)
              if raw[i] > 120 and raw[i + 1] < 90 and raw[i + 2] < 90 and raw[i] - max(raw[i + 1], raw[i + 2]) > 55)
    assert red > 10000, "the mascot was not painted into the artwork"
    svg = (folder / "artwork.svg").read_text(encoding="utf-8")
    assert svg.count("data:image/png;base64,") == 4 and "xmlns:xlink" in svg
    assert "http://" not in svg.replace("http://www.w3.org", "")


def test_a_version_that_lost_its_picture_fails_loudly(artwork, tmp_path):
    folder = tmp_path / "artwork-workspace" / "versions" / "art-cover-lost"
    folder.mkdir(parents=True)
    spec = _spec("cover", [{"type": "image", "asset": "mascot", "x": 0, "y": 0,
                            "width": 400, "height": 500, "opacity": 1}], 1080, 1920)
    artwork._materialise_assets(spec, folder, artwork.available_assets("cover"))
    (folder / "asset-mascot.png").unlink()
    with pytest.raises(artwork.ArtworkError):
        artwork.render(spec, folder)
