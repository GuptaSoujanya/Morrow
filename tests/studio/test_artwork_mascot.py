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
    _png(tmp_path / "mascot" / "cutout.png", 400, 500, "0x7c1411")
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
    him = ["mascot", "mascot-bust", "mascot-head"]
    assert sorted(artwork.available_assets("banner")) == him
    assert sorted(artwork.available_assets("avatar")) == him
    assert sorted(artwork.available_assets("cover", "a-plan", 1)) == ["frame-3", "frame-50", "frame-90"] + him
    assert sorted(artwork.available_assets("cover")) == him
    assert sorted(artwork.available_assets("banner", "a-plan", 1)) == him
    assert sorted(artwork.available_assets("cover", "a-plan", 7)) == him


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


def _ok_spec(kind, width, height, asset="mascot"):
    return _spec(kind, [{"type": "image", "asset": asset, "x": 10, "y": 10,
                         "width": 400, "height": 500, "opacity": 1}], width, height)


def test_codex_draws_first_and_claude_only_stands_in(artwork, monkeypatch):
    monkeypatch.setattr(artwork.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert artwork.bridge_order() == ["codex", "claude"]
    assert artwork.bridge_order("claude") == ["claude", "codex"]
    monkeypatch.setattr(artwork.shutil, "which", lambda name: None if name == "codex" else "/usr/bin/claude")
    assert artwork.bridge_order() == ["claude"]
    monkeypatch.setattr(artwork.shutil, "which", lambda name: None)
    assert artwork.bridge_order() == []


def test_a_signed_out_codex_hands_the_work_to_claude(artwork, monkeypatch):
    monkeypatch.setattr(artwork.shutil, "which", lambda name: f"/usr/bin/{name}")
    asked = []

    def bridge(name, prompt, folder, **rest):
        asked.append(name)
        if name == "codex":
            raise artwork.ArtworkError("Codex could not generate this design: not signed in")
        return _ok_spec("banner", 2560, 1440)
    monkeypatch.setattr(artwork, "_run_bridge", bridge)

    record = artwork.generate("banner", "a bold banner for the channel", mode="shapes")
    assert asked == ["codex", "claude"]
    assert record["bridge"] == "claude"
    assert record["fell_back_from"][0]["bridge"] == "codex"
    assert "not signed in" in record["fell_back_from"][0]["error"]


def test_when_codex_works_claude_is_never_called(artwork, monkeypatch):
    monkeypatch.setattr(artwork.shutil, "which", lambda name: f"/usr/bin/{name}")
    asked = []

    def bridge(name, prompt, folder, **rest):
        asked.append(name)
        return _ok_spec("banner", 2560, 1440)
    monkeypatch.setattr(artwork, "_run_bridge", bridge)

    record = artwork.generate("banner", "a bold banner for the channel", mode="shapes")
    assert asked == ["codex"] and record["bridge"] == "codex" and record["fell_back_from"] == []


def test_both_bridges_failing_is_reported_not_swallowed(artwork, monkeypatch):
    monkeypatch.setattr(artwork.shutil, "which", lambda name: f"/usr/bin/{name}")

    def bridge(name, prompt, folder, **rest):
        raise artwork.ArtworkError(f"{name} is unhappy")
    monkeypatch.setattr(artwork, "_run_bridge", bridge)
    with pytest.raises(artwork.ArtworkError):
        artwork.generate("banner", "a bold banner for the channel", mode="shapes")


def test_closer_framings_are_derived_and_dropped_in_poses_are_picked_up(artwork, tmp_path):
    poses = artwork.mascot_poses()
    assert sorted(poses) == ["mascot-bust", "mascot-head"]
    for key, info in poses.items():
        assert Path(info["path"]).is_file() and Path(info["path"]).parent.name == "poses"
    _png(tmp_path / "mascot" / "poses" / "pointing.png", 300, 400, "green")
    assert "mascot-pointing" in artwork.mascot_poses()
    assert "mascot-pointing" in artwork.available_assets("banner")
    _png(tmp_path / "mascot" / "poses" / "Bad Name!.png", 50, 50, "white")
    assert all(artwork.ASSET_KEY.fullmatch(key) for key in artwork.mascot_poses())


def test_the_brief_asks_for_designed_work_not_a_template(artwork):
    text = artwork._prompt("banner", "bold", "", artwork.brand_context(), None,
                           artwork.available_assets("banner"), None)
    for demand in ("ART DIRECTION", "focal point", "grid", "mascot-head", "Use margins consistently",
                   "Preserve the supplied identity and exact headline", "There is no compulsory palette distribution"):
        assert demand in text, demand
    assert artwork.KIND_DIRECTION["thumbnail"] in artwork._prompt(
        "thumbnail", "bold", "", artwork.brand_context(), None, artwork.available_assets("thumbnail"), None)


MASCOT_PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;padding:0;width:{w}px;height:{h}px;overflow:hidden;background:#0a0b0f}}
h1{{position:absolute;left:{x}px;top:{y}px;margin:0;color:#f4f7ff;font:800 120px/1 Helvetica,sans-serif}}
img{{position:absolute;right:30px;bottom:0;height:{m}px;width:auto}}
</style></head><body><h1 data-art-role="headline">CYBER</h1><img data-art-role="identity" src="mascot.png" alt=""></body></html>"""


def _page(artwork, kind, extra=""):
    width, height = artwork.KINDS[kind]
    x, y = (550, 560) if kind == "banner" else (100, 200) if kind == "cover" else (40, 40)
    return MASCOT_PAGE.format(w=width, h=height, m=int(height * 0.8), x=x, y=y) + extra


def _planning_or_review(mode):
    if mode == "plan":
        return {"idea": "The existing character introduces Cyber Mythic.", "focal_point": "The name.",
                "composition": "Name inside the banner text-safe area; familiar character to the side.",
                "typography": "One bold family with a clear dominant name."}
    if mode == "review":
        return {"pass": True, "issues": [], "strengths": "Fixture verdict for the rendered layout."}
    return None


def test_a_browser_design_may_not_reach_the_internet(artwork):
    assets = artwork.available_assets("banner")
    page = _page(artwork, "banner").replace("<style>", '<link href="https://fonts.googleapis.com/css?family=Inter" rel="stylesheet"><style>')
    problems = artwork._design_problems(page, "banner", assets)
    assert any("internet" in problem for problem in problems)
    assert artwork._design_problems(_page(artwork, "banner"), "banner", assets) == []


def test_the_svg_namespace_is_not_mistaken_for_a_download(artwork):
    page = _page(artwork, "banner", '<svg xmlns="http://www.w3.org/2000/svg"><circle r="5"/></svg>')
    assert artwork._design_problems(page, "banner", artwork.available_assets("banner")) == []


def test_a_browser_design_uses_only_the_pictures_that_exist(artwork):
    assets = artwork.available_assets("banner")
    invented = _page(artwork, "banner").replace("mascot.png", "stock-photo.jpg")
    problems = artwork._design_problems(invented, "banner", assets)
    assert any("does not exist" in problem for problem in problems)
    assert any("mascot does not appear" in problem for problem in problems)


def test_a_cover_is_told_to_show_a_frame_of_its_own_reel(artwork):
    """The frame is asked for in the brief. It is no longer refused at validation, so this covers the brief."""
    assets = artwork.available_assets("cover", "a-plan", 1)
    reel = artwork.reel_facts("a-plan", 1)
    text = artwork._prompt("cover", "a cover", "", artwork.brand_context(), None, assets, reel)
    assert "real frame" in text and "frame-50" in text
    assert artwork._design_problems(_page(artwork, "cover"), "cover", assets) == []
    contract = artwork.design_studio.contract("cover", "Exact title", artwork.design_studio.normalize_brief("cover"))
    assert "meaningful supplied frame, or a specific honest" in contract
    assert "Never fabricate a browser screenshot" in contract
    with_frame = _page(artwork, "cover", '<img src="frame-50.png" alt="">')
    assert artwork._design_problems(with_frame, "cover", assets) == []
    invented = _page(artwork, "cover", '<img src="invented-browser.png" alt="">')
    assert any("does not exist" in problem for problem in artwork._design_problems(invented, "cover", assets))


def test_a_browser_design_is_photographed_at_the_exact_size(artwork, tmp_path):
    folder = tmp_path / "shot"
    folder.mkdir()
    assets = artwork.available_assets("avatar")
    artwork._write_design(folder, _page(artwork, "avatar"), assets)
    report = artwork._shoot(folder, "avatar")
    assert report["ok"] and report["missing"] == [] and report["blocked"] == []
    from PIL import Image
    with Image.open(folder / "artwork.png") as picture:
        assert picture.size == artwork.KINDS["avatar"]
    assert artwork._rendered_problems(folder, "avatar", assets, report) == []


def test_an_empty_page_is_caught_instead_of_being_published(artwork, tmp_path):
    folder = tmp_path / "blank"
    folder.mkdir()
    assets = artwork.available_assets("avatar")
    artwork._write_design(folder, "<!doctype html><html><body style='margin:0;background:#101010'></body></html>", assets)
    report = artwork._shoot(folder, "avatar")
    problems = artwork._rendered_problems(folder, "avatar", assets, report)
    assert any("nearly empty" in problem for problem in problems)
    assert report["diagnostics"]["roles"]["identity"] == []


def test_browser_mode_saves_the_rendered_page_and_what_it_used(artwork, monkeypatch):
    monkeypatch.setattr(artwork.shutil, "which", lambda name: f"/usr/bin/{name}")
    def bridge(name, prompt, folder, mode="shapes", images=None):
        assert images and all(Path(image).is_file() for image in images)
        return _planning_or_review(mode) or {"html": _page(artwork, "banner"), "description": "the eye lands on the name", "alt_text": "a banner"}
    monkeypatch.setattr(artwork, "_run_bridge", bridge)
    record = artwork.generate("banner", "a bold banner for the channel", title="CYBER")
    assert record["origin"] == "html_design" and record["bridge"] == "codex"
    assert record["pictures"] == ["mascot.png"]
    assert "svg" not in record["assets"]
    saved = artwork.HOME / "versions" / record["id"]
    assert (saved / "design.html").is_file() and (saved / "mascot.png").is_file()
    assert artwork.load(record["id"])["spec"]["description"] == "the eye lands on the name"


def test_a_broken_browser_design_gets_one_repair_pass(artwork, monkeypatch):
    monkeypatch.setattr(artwork.shutil, "which", lambda name: f"/usr/bin/{name}")
    seen = []

    def bridge(name, prompt, folder, mode="shapes", images=None):
        if mode != "html":
            return _planning_or_review(mode)
        seen.append(prompt)
        if len(seen) == 1:
            return {"html": _page(artwork, "banner").replace("mascot.png", "https://cdn.example.com/hero.png"),
                    "description": "d", "alt_text": "a"}
        return {"html": _page(artwork, "banner"), "description": "d", "alt_text": "a"}
    monkeypatch.setattr(artwork, "_run_bridge", bridge)

    record = artwork.generate("banner", "a bold banner for the channel", title="CYBER")
    assert record["generation_attempts"] == 2
    assert len(seen) == 2 and "ONE TARGETED REPAIR PASS" in seen[1] and "internet" in seen[1]


def test_the_browser_brief_asks_for_one_offline_self_contained_file(artwork):
    text = artwork._html_prompt("banner", "bold", "Cyber Mythic", artwork.brand_context(), None,
                                artwork.available_assets("banner"), None)
    for demand in ("Complete HTML document", "No scripts, event handlers, frames, external URLs",
                   "JavaScript is disabled", "overflow:hidden", "mascot.png",
                   "appearance and proportions", "Preserve supplied copy verbatim", 'data-art-role="headline"'):
        assert demand in text, demand
