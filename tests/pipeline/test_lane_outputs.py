"""Pipeline subprocess output paths stay independent even within one run."""
from pipeline import lanes


def test_all_sites_get_separate_outputs_with_one_shared_read_library(tmp_path, monkeypatch):
    output = tmp_path / "resume" / "runs" / "run-1"
    library = tmp_path / "resume"
    monkeypatch.setenv("RESUME_OUT_DIR", str(output))
    monkeypatch.setenv("MORROW_RESUME_LIBRARY_DIR", str(library))
    monkeypatch.setattr(lanes, "_prepare_browser", lambda site, base: {})
    environments = {site: lanes.prepare(site, "") for site in ("naukri", "linkedin", "hirist", "instahyre")}
    for site, environment in environments.items():
        assert environment == {
            "RESUME_OUT_DIR": str(output / "lanes" / site),
            "MORROW_RESUME_LIBRARY_DIR": str(library),
        }
    assert len({env["RESUME_OUT_DIR"] for env in environments.values()}) == 4
    assert not output.exists()


def test_unscoped_pipeline_preserves_its_original_output_as_read_library(tmp_path, monkeypatch):
    monkeypatch.setenv("RESUME_OUT_DIR", str(tmp_path / "resume"))
    monkeypatch.delenv("MORROW_RESUME_LIBRARY_DIR", raising=False)
    monkeypatch.setattr(lanes, "_prepare_browser", lambda site, base: {"BROWSER_PROFILE_DIR": "/private/synthetic"})
    assert lanes.prepare("cutshort", "") == {
        "BROWSER_PROFILE_DIR": "/private/synthetic",
        "RESUME_OUT_DIR": str(tmp_path / "resume" / "lanes" / "cutshort"),
        "MORROW_RESUME_LIBRARY_DIR": str(tmp_path / "resume"),
    }
