import json

from common import profile_record
from common.models import Settings
from common.profile_plan import AtsReport, ProfilePlan
from sites_bot.profile_agent import ProfileCheck, Section


def _result(saved=True):
    return ProfileCheck(
        saved=saved, why="confirmed on the reloaded page",
        completeness_before="82%", completeness_after="100%",
        sections=[
            Section(name="Resume headline", action="updated", before="old",
                    after="AI Engineer | Python", on_page=True),
            Section(name="Key skills", action="filled", after="LangChain, FastAPI, AWS Bedrock",
                    on_page=False, missing=["AWS Bedrock"]),
            Section(name="Education", action="already_ok", before="B.Tech"),
        ])


def _plan():
    return ProfilePlan(headline="AI Engineer | Python", key_skills=["LangChain", "FastAPI"],
                       ats=AtsReport(score=74, keyword_score=70, structure_score=80))


def test_a_digest_is_flat_and_always_has_the_same_keys():
    record = profile_record.digest("naukri", "Naukri", _result(), _plan())
    assert set(profile_record.FIELDS) <= set(record)
    assert record["board"] == "naukri" and record["saved"] is True and record["ats_score"] == 74
    assert record["changed"] == 2 and record["confirmed"] == 1
    assert record["unconfirmed"] == ["Key skills"] and record["missing"] == ["AWS Bedrock"]
    assert [s["confirmed"] for s in record["sections"]] == [True, False, None]
    assert record["sections"][1]["missing"] == ["AWS Bedrock"]


def test_a_digest_survives_a_run_with_no_plan():
    record = profile_record.digest("hirist", "Hirist", _result(saved=False), None)
    assert set(profile_record.FIELDS) <= set(record)
    assert record["ats_score"] is None and record["headline"] == "" and record["skills"] == []


def test_the_index_keeps_the_latest_per_board_and_every_run_in_history(tmp_path):
    first = profile_record.digest("naukri", "Naukri", _result(), _plan())
    second = dict(first, at="2026-10-26T10:00:00", saved=False)
    third = profile_record.digest("hirist", "Hirist", _result(), _plan())
    for record in (first, second, third):
        profile_record.save(record, tmp_path)

    latest = profile_record.load(tmp_path)
    assert sorted(latest) == ["hirist", "naukri"]
    assert latest["naukri"]["saved"] is False, "the newer run replaces the older one"
    assert len(profile_record.history(tmp_path)) == 3
    assert len(profile_record.history(tmp_path, "naukri")) == 2
    assert json.loads((tmp_path / profile_record.LATEST).read_text())["hirist"]["board"] == "hirist"


def test_a_missing_or_broken_index_reads_as_empty(tmp_path):
    assert profile_record.load(tmp_path) == {} and profile_record.history(tmp_path) == []
    (tmp_path / profile_record.LATEST).write_text("not json")
    (tmp_path / profile_record.HISTORY).write_text("not json\n")
    assert profile_record.load(tmp_path) == {} and profile_record.history(tmp_path) == []


def test_the_index_sits_beside_the_run_folders():
    assert profile_record.index_dir(Settings(report_dir="/tmp/runs")).as_posix() == "/tmp/runs/profile"
    assert profile_record.index_dir(None).as_posix() == "user/reports/profile"


def test_the_table_and_detail_are_short_enough_to_read(tmp_path):
    profile_record.save(profile_record.digest("naukri", "Naukri", _result(), _plan()), tmp_path)
    table = profile_record.table(profile_record.load(tmp_path))
    assert len(table.splitlines()) == 2 and "Naukri" in table and "1/2" in table
    assert "Key skills" in table and "74" in table

    detail = profile_record.detail(profile_record.load(tmp_path)["naukri"])
    assert "NO  Key skills" in detail and "not on the page: AWS Bedrock" in detail
    assert "ok  Resume headline" in detail and "Resume ATS 74/100" in detail


def test_the_table_names_a_value_that_did_not_land_when_every_section_is_there(tmp_path):
    """A skill missing from an otherwise saved section is the whole point of reading the table."""
    partial = ProfileCheck(saved=True, why="confirmed on the reloaded page, except: AWS Bedrock",
                           sections=[Section(name="Key skills", action="filled", on_page=True,
                                             after="LangChain, FastAPI, AWS Bedrock, Go",
                                             missing=["AWS Bedrock"])])
    profile_record.save(profile_record.digest("naukri", "Naukri", partial, _plan()), tmp_path)
    table = profile_record.table(profile_record.load(tmp_path))
    assert "saved" in table and "AWS Bedrock" in table


def test_the_cli_prints_the_table_a_board_and_json(tmp_path, capsys):
    profile_record.save(profile_record.digest("naukri", "Naukri", _result(), _plan()), tmp_path)
    where = ["--dir", str(tmp_path)]

    assert profile_record.main(where) == 0
    assert "NOT ON PAGE" in capsys.readouterr().out

    assert profile_record.main(where + ["--board", "naukri"]) == 0
    assert "not on the page: AWS Bedrock" in capsys.readouterr().out

    assert profile_record.main(where + ["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["naukri"]["confirmed"] == 1

    assert profile_record.main(where + ["--board", "nowhere"]) == 1
    assert "No profile update recorded" in capsys.readouterr().out


def test_the_cli_says_so_when_nothing_has_run(tmp_path, capsys):
    assert profile_record.main(["--dir", str(tmp_path)]) == 0
    assert "No profile update has been recorded yet" in capsys.readouterr().out


def _score_result():
    return ProfileCheck(
        saved=False, why="2 of 3 planned sections are on the profile; not on it: Projects",
        completeness_after="93%",
        sections=[
            Section(name="Resume headline", action="checked", after="AI Engineer | Python", on_page=True),
            Section(name="Key skills", action="checked", after="LangChain, FastAPI", on_page=True,
                    missing=["FastAPI"]),
            Section(name="Projects", action="checked", after="EvalAgentFlow", on_page=False),
        ])


def test_a_score_counts_the_planned_sections_it_checked_not_changes():
    record = profile_record.digest("naukri", "Naukri", _score_result(), _plan(), kind=profile_record.SCORE)
    assert record["kind"] == "score" and record["saved"] is False
    assert record["changed"] == 3 and record["confirmed"] == 2
    assert record["unconfirmed"] == ["Projects"] and record["missing"] == ["FastAPI"]
    assert profile_record.digest("naukri", "Naukri", _result(), _plan())["kind"] == "run"


def test_the_table_and_detail_call_a_score_by_its_name():
    record = profile_record.digest("naukri", "Naukri", _score_result(), _plan(), kind=profile_record.SCORE)
    table = profile_record.table({"naukri": record})
    assert "GAPS" in table and "2/3" in table and "? -> 93%" in table and "NOT SAVED" not in table
    detail = profile_record.detail(record)
    assert detail.startswith("Naukri profile score - GAPS (")
    assert "NO  Projects" in detail and "not on the page: FastAPI" in detail
    full = dict(record, saved=True)
    assert "MATCHES RESUME" in profile_record.table({"naukri": full})
    assert profile_record.detail(_result_record()).startswith("Naukri profile - saved (")


def _result_record():
    return profile_record.digest("naukri", "Naukri", _result(), _plan())
