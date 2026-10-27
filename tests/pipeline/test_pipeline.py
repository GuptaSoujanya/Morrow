"""The morning pipeline: its .memory checkpoint, stage selection and the learning files."""

import argparse
from datetime import date
from pathlib import Path

import pytest

from common import ai_cli
from common.memory import DONE, FAILED, Memory
from common.models import ApplyStatus
from pipeline import briefing, content, lanes, learning, links, run

DAY = date(2026, 10, 22)


def _args(**kw):
    base = dict(fresh=False, dry_run=False, env=None, verbose=False, cli=None, only=[], skip=[], redo=False,
                agents=2, bots=1, containers=False, no_watch=True, today=DAY)
    base.update(kw)
    return argparse.Namespace(**base)


def _week(week):
    days = learning.days_of(week)
    return "# Week %d: t\n\nintro\n\n" % week + "".join(
        "## Day %d: d%d\n\n**System Design: sd%d** (55 min)\nx\n\n**ML / GenAI: ml%d** (55 min)\ny\n\n"
        "**Recall** (10 min)\n- q\n\n**Go deeper**\n- [a](http://a)\n\n" % (d, d, d, d) for d in days)


def test_memory_marks_and_reloads(tmp_path):
    mem = Memory(tmp_path, DAY)
    mem.plan(["profile:naukri", "apply:naukri"])
    mem.mark("profile:naukri", DONE)
    mem.mark("apply:naukri", FAILED, "exit 3")
    again = Memory(tmp_path, DAY)
    assert again.is_done("profile:naukri")
    assert not again.is_done("apply:naukri")
    assert again.stage("apply:naukri")["attempts"] == 1
    assert "[x] profile:naukri" in (tmp_path / "2026-10-22.md").read_text()
    assert (tmp_path / "README.md").exists()
    assert not Memory(tmp_path, date(2026, 10, 23)).is_done("profile:naukri")


def test_sync_applied_keeps_only_verified_once(tmp_path):
    mem = Memory(tmp_path, DAY)
    mem.sync_applied([
        {"job_id": "1", "company": "Acme", "title": "SWE", "status": ApplyStatus.APPLIED},
        {"job_id": "1", "company": "Acme", "title": "SWE", "status": ApplyStatus.APPLIED},
        {"job_id": "2", "company": "Beta", "title": "ML", "status": ApplyStatus.APPLIED_PLATFORM},
        {"job_id": "3", "company": "Gone", "title": "X", "status": ApplyStatus.EXTERNAL_SKIPPED},
    ])
    assert [row["company"] for row in mem.today["applied"]] == ["Acme", "Beta"]
    assert "Applied today (2)" in mem.markdown()


def test_run_day_continues_where_it_stopped(tmp_path):
    calls = []

    def stage(name, code):
        return run.Stage(name, lambda: calls.append(name) or code)

    mem = Memory(tmp_path, DAY)
    stages = [stage("profile:naukri", 0), stage("learn", 3), stage("apply:naukri", 0)]
    assert run.run_day(_args(), stages, mem) == run.EXIT_FAILED
    assert sorted(calls) == ["apply:naukri", "learn", "profile:naukri"]
    assert calls.index("profile:naukri") < calls.index("apply:naukri")
    assert Memory(tmp_path, DAY).day_status() == "in progress"
    calls.clear()
    stages[1] = stage("learn", 0)
    assert run.run_day(_args(), stages, Memory(tmp_path, DAY)) == run.EXIT_OK
    assert calls == ["learn"]
    again = Memory(tmp_path, DAY)
    assert again.day_status() == "done" and again.today["completed_at"]
    assert "**Day: DONE** (3 of 3 stages done)" in (tmp_path / "2026-10-22.md").read_text()
    calls.clear()
    assert run.run_day(_args(), stages, Memory(tmp_path, DAY)) == run.EXIT_OK
    assert calls == []
    # --redo runs only the chosen stages again and keeps the others done.
    assert run.run_day(_args(redo=True), [stages[1]], Memory(tmp_path, DAY), [s.name for s in stages]) == run.EXIT_OK
    assert calls == ["learn"] and Memory(tmp_path, DAY).day_status() == "done"
    calls.clear()
    run.run_day(_args(fresh=True), stages, Memory(tmp_path, DAY))
    assert sorted(calls) == ["apply:naukri", "learn", "profile:naukri"]
    assert calls.index("profile:naukri") < calls.index("apply:naukri")


def test_a_done_stage_whose_file_is_gone_runs_again(tmp_path):
    out = tmp_path / "out.md"
    calls = []

    def work():
        calls.append(1)
        out.write_text("x")
        return 0

    stages = [run.Stage("brief:goal", work, True, (out,))]
    assert run.run_day(_args(), stages, Memory(tmp_path / "m", DAY)) == run.EXIT_OK
    out.unlink()
    mem = Memory(tmp_path / "m", DAY)
    assert not mem.is_done("brief:goal") and mem.day_status() == "in progress"
    assert run.run_day(_args(), stages, mem) == run.EXIT_OK
    assert len(calls) == 2
    lying = [run.Stage("brief:papers", lambda: 0, True, (tmp_path / "never.md",))]
    assert run.run_day(_args(), lying, Memory(tmp_path / "m", DAY)) == run.EXIT_FAILED


def test_agents_run_in_parallel_with_the_browser_stages(tmp_path):
    import threading
    gate = threading.Barrier(3, timeout=5)

    def meet():
        gate.wait()  # only passes when all three run at the same time
        return 0

    stages = [run.Stage("apply:naukri", meet), run.Stage("brief:goal", meet, True),
              run.Stage("brief:papers", meet, True)]
    assert run.run_day(_args(), stages, Memory(tmp_path, DAY)) == run.EXIT_OK


def test_bots_start_while_learn_runs_and_the_agents_wait_for_it(tmp_path):
    import threading
    gate = threading.Barrier(2, timeout=5)  # learn and apply:naukri must run at the same time
    learnt = threading.Event()

    def learn():
        gate.wait()
        learnt.set()
        return 0

    def brief():
        assert learnt.is_set(), "the agents wait for learn"
        return 0

    stages = [run.Stage("learn", learn), run.Stage("apply:naukri", lambda: gate.wait() and 0),
              run.Stage("brief:goal", brief, True), run.Stage("brief:papers", brief, True)]
    assert run.run_day(_args(agents=1), stages, Memory(tmp_path, DAY)) == run.EXIT_OK
    assert all(Memory(tmp_path, DAY).is_done(s.name) for s in stages)


def test_every_site_runs_at_once_by_default(tmp_path, monkeypatch):
    import threading
    base = tmp_path / "browser" / "naukri"
    (base / "chrome").mkdir(parents=True)
    (base / "chrome" / "Cookies").write_text("session")
    from common.connections import mark_managed
    mark_managed(base)
    monkeypatch.setattr(run, "base_profile", lambda env: str(base))
    gate = threading.Barrier(3, timeout=5)  # all three sites' profile stages at the same time
    monkeypatch.setattr(lanes, "run_isolated", lambda lane, command, env, container=False: gate.wait() and 0)
    stages = [run._bot("profile:%s" % site, "%s_bot.update_profile" % site, [], lambda: 1)
              for site in ("naukri", "hirist", "instahyre")]
    assert run.run_day(_args(bots=None), stages, Memory(tmp_path / "m", DAY)) == run.EXIT_OK
    monkeypatch.delenv("PIPELINE_BOTS", raising=False)
    assert run.parse_args([]).bots is None and run.parse_args([]).agents == run.AGENTS_AT_ONCE == 6
    monkeypatch.setenv("PIPELINE_BOTS", "2")
    assert run.parse_args([]).bots == 2



def test_bots_run_each_site_in_its_own_process_and_profile(tmp_path, monkeypatch):
    import threading
    base = tmp_path / "browser" / "naukri"
    (base / "chrome").mkdir(parents=True)
    (base / "chrome" / "Cookies").write_text("session")
    from common.connections import mark_managed
    mark_managed(base)
    monkeypatch.setattr(run, "base_profile", lambda env: str(base))
    gate = threading.Barrier(2, timeout=5)  # both sites' first stages must run at the same time
    seen = []

    def fake(lane, command, env, container=False):
        assert not container
        if command[0].endswith("update_profile"):
            gate.wait()
        seen.append((lane, command[0], env.get("BROWSER_PROFILE_DIR")))
        return 0

    monkeypatch.setattr(lanes, "run_isolated", fake)
    stages = [run._bot("profile:naukri", "naukri_bot.update_profile", [], lambda: 1),
              run._bot("profile:hirist", "hirist_bot.update_profile", [], lambda: 1),
              run._bot("apply:naukri", "naukri_bot.cli", [], lambda: 1),
              run._bot("apply:hirist", "hirist_bot.cli", [], lambda: 1)]
    mem = Memory(tmp_path / "m", DAY)
    assert run.run_day(_args(bots=2), stages, mem) == run.EXIT_OK
    assert all(mem.is_done(s.name) for s in stages)
    hirist = str(tmp_path / "browser" / "lanes" / "hirist")
    assert [s for s in seen if s[0] == "hirist"] == [("hirist", "hirist_bot.update_profile", hirist),
                                                    ("hirist", "hirist_bot.cli", hirist)]
    assert [s[1] for s in seen if s[0] == "naukri"] == ["naukri_bot.update_profile", "naukri_bot.cli"]
    assert all(s[2] is None for s in seen if s[0] == "naukri")  # Naukri keeps its own profile
    copied = tmp_path / "browser" / "lanes" / "hirist" / "chrome"
    assert (copied / "Cookies").read_text() == "session"


def test_containers_run_every_site_at_once_each_in_its_own_container(tmp_path, monkeypatch):
    import threading
    monkeypatch.setattr(run, "base_profile", lambda env: pytest.fail("containers keep their own profiles"))
    monkeypatch.setattr(run, "WATCH_PAGE", tmp_path / "watch.html")
    gate = threading.Barrier(3, timeout=5)  # all three sites at once, though --bots is 1
    seen = []

    def fake(lane, command, env, container=False):
        gate.wait()
        seen.append((lane, command[0], env, container))
        return 0

    monkeypatch.setattr(lanes, "run_isolated", fake)
    stages = [run._bot("profile:%s" % site, "%s_bot.update_profile" % site, [], lambda: 1)
              for site in ("naukri", "hirist", "instahyre")]
    assert run.run_day(_args(containers=True), stages, Memory(tmp_path / "m", DAY)) == run.EXIT_OK
    assert sorted(seen) == [(site, "%s_bot.update_profile" % site, {}, True)
                            for site in ("hirist", "instahyre", "naukri")]
    page = (tmp_path / "watch.html").read_text()
    assert all("http://localhost:%d/vnc.html" % lanes.WATCH_PORTS[s] in page for s in ("naukri", "hirist"))


def test_every_site_has_its_container_on_its_watch_port():
    import yaml
    compose = yaml.safe_load((Path(__file__).parents[2] / "docker-compose.yml").read_text())
    for site, port in lanes.WATCH_PORTS.items():
        service = compose["services"][site]
        assert service["ports"] == ["127.0.0.1:%d:6080" % port]
        assert service["environment"]["SITE"] == site
    from sites_bot.platforms import BOARDS
    assert set(BOARDS) <= set(lanes.WATCH_PORTS)
    argv = lanes.in_container("hirist", ("hirist_bot.cli", "--dry-run"))
    assert argv[:2] == ["docker", "compose"] and argv[-5:] == ["hirist", "python3", "-m", "hirist_bot.cli", "--dry-run"]


def test_lanes_group_by_site_and_run_the_bot_as_a_child(capsys):
    assert lanes.group(["profile:naukri", "profile:hirist", "apply:naukri", "apply:hirist"]) == [
        ["profile:naukri", "apply:naukri"], ["profile:hirist", "apply:hirist"]]
    assert "BROWSER_PROFILE_DIR" not in lanes.prepare("linkedin", "user/browser/naukri")
    assert lanes.run_isolated("hirist", ("calendar", "2026", "1"), {"BROWSER_PROFILE_DIR": "x"}) == 0
    assert "[hirist]" in capsys.readouterr().err
    assert all(s.command for s in run.build_stages(_args(), ["hirist"]) if s.name.split(":")[0] in ("profile", "apply"))


def test_a_crashing_stage_does_not_stop_the_day(tmp_path):
    def boom():
        raise RuntimeError("no browser")

    mem = Memory(tmp_path, DAY)
    assert run.run_day(_args(), [run.Stage("apply:hirist", boom), run.Stage("learn", lambda: 0)], mem) == run.EXIT_FAILED
    assert mem.stage("apply:hirist")["detail"] == "crashed: no browser"
    assert mem.is_done("learn")


def test_stage_order_and_selection():
    names = [s.name for s in run.build_stages(_args(), ["hirist", "instahyre"])]
    assert names == ["learn", "profile:naukri", "profile:linkedin", "profile:hirist", "profile:instahyre",
                     "apply:naukri",
                     "apply:hirist", "apply:instahyre", "research:resume", "brief:goal",
                     "brief:system-design", "brief:papers", "brief:tech-news", "brief:companies"]
    stages = run.build_stages(_args(), ["hirist"])
    assert [s.name for s in run.selected(stages, ["profile"], [])] == ["profile:naukri", "profile:linkedin",
                                                                       "profile:hirist"]
    assert [s.name for s in run.selected(stages, ["brief"], [])][0] == "brief:goal"
    assert "apply:naukri" not in [s.name for s in run.selected(stages, [], ["apply:naukri"])]


def test_board_stages_run_each_boards_own_bot(monkeypatch):
    from hirist_bot import cli as hirist_cli, update_profile as hirist_profile

    seen = []
    monkeypatch.setattr(hirist_profile, "main", lambda flags: seen.append(("profile", flags)) or 0)
    monkeypatch.setattr(hirist_cli, "main", lambda flags: seen.append(("apply", flags)) or 0)
    work = {s.name: s.work for s in run.build_stages(_args(dry_run=True), ["hirist"])}
    work["profile:hirist"]()
    work["apply:hirist"]()
    assert seen == [("profile", ["--dry-run", "--create-profile"]), ("apply", ["--dry-run"])]


def test_naukri_and_linkedin_profile_stages_use_the_browser_agent(monkeypatch):
    from linkedin_bot import update_profile as linkedin_profile
    from naukri_bot import update_profile as naukri_profile

    seen = []
    monkeypatch.setattr(naukri_profile, "main", lambda flags: seen.append(("naukri", flags)) or 0)
    monkeypatch.setattr(linkedin_profile, "main", lambda flags: seen.append(("linkedin", flags)) or 0)
    work = {s.name: s.work for s in run.build_stages(_args(dry_run=True), [])}
    work["profile:naukri"]()
    work["profile:linkedin"]()
    assert seen == [("naukri", ["--dry-run", "--review"]), ("linkedin", ["--dry-run"])]


def test_write_today_cuts_the_day_and_moves_on_after_done(tmp_path):
    (tmp_path / "weeks").mkdir()
    (tmp_path / "weeks" / "week-01.md").write_text(_week(1))
    day, path = learning.write_today(lambda prompt: pytest.fail("no CLI needed"), tmp_path, DAY)
    assert day == 1 and "## Day 1: d1" in path.read_text() and "Day 2" not in path.read_text()
    assert learning.mark_done(tmp_path, DAY) == 1
    day, _ = learning.write_today(lambda prompt: "", tmp_path, DAY)
    assert day == 2
    assert "System Design: sd2" in learning.today_topics(tmp_path)


def test_missing_week_is_written_and_checked(tmp_path):
    prompts = []
    path = learning.ensure_week(13, lambda p: prompts.append(p) or "```markdown\n" + _week(13) + "```", tmp_path)
    assert "Day 85 to Day 90" in prompts[0]
    assert set(learning.split_days(path.read_text())) == set(range(85, 91))
    with pytest.raises(ai_cli.AIError):
        learning.ensure_week(12, lambda p: "# Week 12\n\n## Day 78: only one\n", tmp_path)
    assert not learning.week_path(12, tmp_path).exists()


def test_resume_learning_fills_only_missing_and_hides_contacts(tmp_path, monkeypatch):
    resume = tmp_path / "base.tex"
    resume.write_text("Soujanya\nmail@example.com\nPython, FastAPI\n")
    root = tmp_path / "rl"
    root.mkdir()
    monkeypatch.setattr(learning, "resume_areas", lambda resume_path=None: [
        ("01", "python", "Python"), ("02", "whisper-and-aws", "Whisper and AWS")])
    (root / "01-python.md").write_text("# Area 01\n")
    prompts = []
    written = learning.fill_resume_learning(
        lambda p: prompts.append(p) or "# Whisper\n\n## Interview questions and answers\n", root, resume)
    assert len(written) == 2 and written[0].name.startswith("01-python-")
    assert written[1].name == "02-whisper-and-aws.md"
    assert (root / "01-python.md").read_text() == "# Area 01\n"
    assert "example.com" not in prompts[0] and "FastAPI" in prompts[0]
    assert "[Whisper](02-whisper-and-aws.md)" in (root / "README.md").read_text()


def test_briefing_agent_needs_graphs_and_links_then_indexes(tmp_path):
    agent = briefing.by_key("papers")
    good = ("# Papers to read\n\n## A (2025)\nhttps://arxiv.org/abs/1 https://arxiv.org/abs/2 "
            "https://arxiv.org/abs/3 https://arxiv.org/abs/4 https://arxiv.org/abs/5\n\n"
            "```mermaid\nmindmap\n```\n\n```mermaid\nflowchart LR\nA-->B\n```\n")
    prompts = []
    root = tmp_path / "daily"
    path = briefing.run_agent(agent, lambda p: prompts.append(p) or "Sure!\n" + good, DAY, "ctx", root)
    assert path == root / "2026-10-22" / "03-papers.md" and path.read_text().startswith("# Papers")
    assert prompts[0].startswith("ctx") and "mermaid" in prompts[0] and "from 2024 to 2026" in prompts[0]
    with pytest.raises(ai_cli.AIError):
        briefing.run_agent(briefing.by_key("goal"), lambda p: "# Today's goal\n", DAY, "ctx", root)
    assert not (root / "2026-10-22" / "01-goal.md").exists()
    index = briefing.write_index(DAY, {"brief:papers": {"status": DONE}}, [("2026-10-21", 2), ("2026-10-22", 5)],
                                 [{"company": "Acme"}], root, tmp_path / "learning")
    text = index.read_text()
    assert "[03-papers.md](03-papers.md)" in text and "| goal | not run | - |" in text
    assert "bar [2, 5]" in text and "pie title 90-day plan" in text and "Acme" in text
    assert (tmp_path / "TODAY.md").exists()


def test_claude_and_kiro_research_together_and_one_merges(tmp_path):
    agent = briefing.by_key("tech-news")
    links_ = " ".join("https://news.example/%d" % n for n in range(6))
    good = "# Tech news\n\n## Models and labs\n%s\n\n```mermaid\npie\n```\n" % links_
    asked = {"claude": [], "kiro": []}

    def cli(name, answer):
        return lambda p: asked[name].append(p) or answer

    root = tmp_path / "daily"
    team = {"claude": cli("claude", good + "claude\n"), "kiro": cli("kiro", good + "kiro\n")}
    text = briefing.run_agent(agent, team, DAY, "ctx", root).read_text()
    assert len(asked["kiro"]) == 1 and len(asked["claude"]) == 2  # claude drafts, then merges
    merge = asked["claude"][1]
    assert "--- Draft by claude ---" in merge and "--- Draft by kiro ---" in merge and agent.brief in merge
    assert text.endswith("*Researched by claude and kiro; merged by claude.*\n")

    # A draft that fails its check is left out; the other one is the file.
    text = briefing.run_agent(agent, {"claude": lambda p: "# Tech news\n", "kiro": cli("kiro", good)},
                              DAY, "ctx", root).read_text()
    assert text == links.linkify(good)

    # A merge that fails its check keeps the first good draft.
    answers = iter([good + "first\n", "# Tech news\n"])
    text = briefing.run_agent(agent, {"claude": lambda p: next(answers), "kiro": cli("kiro", good)},
                              DAY, "ctx", root).read_text()
    assert text == links.linkify(good + "first\n")

    with pytest.raises(ai_cli.AIError, match="claude.*kiro"):
        briefing.run_agent(agent, {"claude": lambda p: "x", "kiro": lambda p: "y"}, DAY, "ctx", root)


def test_the_team_is_both_clis_by_default(monkeypatch):
    monkeypatch.delenv("PIPELINE_AI_CLI", raising=False)
    monkeypatch.setattr(ai_cli.shutil, "which", lambda name: "/bin/" + name)
    assert ai_cli.team() == ["claude", "kiro"] and ai_cli.team("kiro") == ["kiro"]
    assert ai_cli.chosen_cli("both") == "claude"
    monkeypatch.setattr(ai_cli.shutil, "which", lambda name: "/bin/kiro-cli" if name == "kiro-cli" else None)
    assert ai_cli.team() == ["kiro"] and list(learning.researchers()) == ["kiro"]


def test_cli_commands(monkeypatch):
    monkeypatch.setattr(ai_cli.shutil, "which", lambda name: "/bin/" + name)
    assert ai_cli.chosen_cli("kiro") == "kiro"
    assert ai_cli.command_for("kiro", "hi")[:3] == ["kiro-cli", "chat", "--no-interactive"]
    claude = ai_cli.command_for("claude", "hi")
    assert claude[:3] == ["claude", "-p", "hi"] and "WebSearch,WebFetch" in claude
    offline = ai_cli.command_for("claude", "hi", web=False)
    assert offline[offline.index("--tools") + 1] == "" and "WebSearch" not in offline
    assert "--trust-tools=" in ai_cli.command_for("kiro", "hi", web=False)
    monkeypatch.setattr(ai_cli.shutil, "which", lambda name: None)
    with pytest.raises(ai_cli.AIError):
        ai_cli.ask("hi")


def test_checkpoint_links_profiles_and_jobs(tmp_path):
    from common import memory

    memory.record_profile("instahyre", memory.PROFILE_CREATED, "https://www.instahyre.com/candidate/profile/",
                          folder=tmp_path)
    mem = Memory(tmp_path, date(2026, 10, 22))
    mem.sync_applied([{"job_id": "1", "company": "Acme", "title": "SDE", "url": "https://x/job/1",
                       "status": ApplyStatus.APPLIED_PLATFORM}])
    text = (tmp_path / "2026-10-22.md").read_text()
    assert "| instahyre | [open](https://www.instahyre.com/candidate/profile/) | created |" in text
    assert "- Acme: [SDE](https://x/job/1)" in text


def test_board_profile_stage_creates_missing_profiles(monkeypatch):
    calls = []
    monkeypatch.setattr(run, "_board_bot", lambda name, tool, flags: calls.append((name, tool, flags)) or 0)
    stages = {s.name: s for s in run.build_stages(_args(), ["hirist"])}
    stages["profile:hirist"].work()
    assert calls == [("hirist", "update_profile", ["--create-profile"])]


def test_linkify_makes_list_links_and_leaves_code_and_lines_alone():
    from pipeline import links

    text = ("- CLIP paper, Radford 2021 — https://arxiv.org/abs/2103.00020\n\n"
            "- Interview chapter: ../../../course/a.md\n"
            "See https://x.dev/y. and [ok](https://z.dev)\n"
            "```python\nurl = 'https://in.code'\n```\n")
    out = links.linkify(text)
    assert "- [CLIP paper, Radford 2021](https://arxiv.org/abs/2103.00020)\n\n" in out
    assert "- [Interview chapter](../../../course/a.md)" in out
    assert "See [https://x.dev/y](https://x.dev/y). and [ok](https://z.dev)" in out
    assert "url = 'https://in.code'" in out and out.count("\n") == text.count("\n")
    assert links.linkify(out) == out


def test_relink_moves_relative_links_between_folders(tmp_path):
    from pipeline import links

    text = "[c](../../../course/a.md#x) [w](https://w.dev) [h](#top)"
    moved = links.relink(text, tmp_path / "r" / "learning" / "weeks", tmp_path / "r" / "learning")
    assert moved == "[c](../../course/a.md#x) [w](https://w.dev) [h](#top)"


def test_week_check_finds_missing_days_parts_links_and_stray_headings(tmp_path):
    from pipeline import content

    week = _week(1).replace("## Day 3: d3", "## Notes\n\n## Day 3: d3").replace("**ML / GenAI: ml4**", "")
    week = week.replace("## Day 7: d7", "## Day 8: d7").replace("- [a](http://a)\n\n## Day 2", "- none\n\n## Day 2")
    learning.week_path(1, tmp_path).parent.mkdir(parents=True)
    learning.week_path(1, tmp_path).write_text(week)
    problems = "\n".join(content.week_problems(1, tmp_path))
    assert "stray heading '## Notes'" in problems and "day 4 has no ML / GenAI" in problems
    assert "wanted [1, 2, 3, 4, 5, 6, 7]" in problems and "day 1 has no link under Go deeper" in problems
    learning.week_path(1, tmp_path).write_text(_week(1))
    assert content.week_problems(1, tmp_path) == []


def test_papers_must_be_from_the_last_two_years():
    agent = briefing.by_key("papers")
    body = "".join("https://example.org/%d\n" % n for n in range(5)) + "```mermaid\n```\n" * 2
    briefing.check(agent, "# Papers to read\n\n## New (2024)\n## Reading order\n" + body, DAY)
    for old in ("## NumPy (2020)\n", "## X (2025)\nhttps://arxiv.org/abs/2006.10256\n"):
        with pytest.raises(ai_cli.AIError, match="before 2024"):
            briefing.check(agent, "# Papers to read\n\n" + old + body, DAY)
    assert briefing.old_papers("## Tools (2026)\nhttps://arxiv.org/abs/2608.11434", 2024) == []


def _fake_cli(prompt):
    """A stand-in for claude/kiro: a valid answer for whichever writer asked."""
    if prompt.startswith("Write week "):
        week = int(prompt.split()[2])
        return _week(week).replace("- [a](http://a)", "- [course](../../../../database/course/x.md) and https://a.dev/%d" % week)
    agent = next(a for a in briefing.AGENTS if briefing.brief_for(a) in prompt)
    heading = agent.heading + (" caching" if agent.heading.endswith(":") else "")
    return heading + "\n\n" + "".join("```mermaid\npie\n```\n" for _ in range(agent.graphs)) + "".join(
        "- source https://example.org/%s/%d\n" % (agent.key, n) for n in range(agent.links))


def test_the_pipeline_writes_and_checks_the_material_for_the_date_it_runs(tmp_path, monkeypatch):
    from pipeline import content

    (tmp_path / "database" / "course").mkdir(parents=True)
    (tmp_path / "database" / "course" / "x.md").write_text("# x")
    monkeypatch.setattr(learning, "ask_cli", lambda cli=None: _fake_cli)
    monkeypatch.setattr(run, "board_names", lambda env: [])
    for day in ("2026-10-23", "2026-10-24"):
        code = run.main(["run", "--only", "learn", "--only", "brief", "--date", day])
        assert code == 0
        assert content.day_problems(date.fromisoformat(day)) == []
        assert (learning.LEARNING / "daily" / ("%s.md" % day)).read_text().startswith("# %s: Day 1 " % day)
        assert day in (learning.RESEARCH / "TODAY.md").read_text()
        assert Memory(run.MEMORY_DIR, date.fromisoformat(day)).is_done("brief:papers")
    assert (briefing.DAILY / "2026-10-23" / "01-goal.md").exists()  # the day before is kept
    assert "[course](../../../database/course/x.md)" in (learning.LEARNING / "today.md").read_text()
    assert run.main(["check", "--date", "2026-10-25"]) == 3


def _course(root):
    (root / "course" / "01-system-design").mkdir(parents=True)
    (root / "course" / "02-dsa").mkdir()
    (root / "course" / "_sidebar.md").write_text(
        "- [1.1 Fundamentals](01-system-design/01-fundamentals.md)\n- [2.1 Arrays](02-dsa/01-arrays.md)\n")
    (root / "course" / "01-system-design" / "01-fundamentals.md").write_text(
        "# Fundamentals\n\n## Load Balancers\n\nSpread requests.\n\n### Algorithms\n\nRound robin, see "
        "[arrays](../02-dsa/01-arrays.md).\n\n```\n## not a heading\n```\n\n## Caching hot data\n\nKeep it near.\n")
    (root / "course" / "02-dsa" / "01-arrays.md").write_text("# Arrays\n\n## Two sums\n\nHash it.\n")
    weeks = root / "learning" / "weeks"
    weeks.mkdir(parents=True)
    return root / "course", root / "learning", weeks


def test_course_reading_quotes_linked_sections_and_a_chapter_the_plan_skips(tmp_path):
    from pipeline import course

    course_root, learning_root, weeks = _course(tmp_path)
    day = ("## Day 1: Load balancers\n\n**System Design: Load balancers** (55 min)\n\n"
           "Read [lb](../../course/01-system-design/01-fundamentals.md#load-balancers).\n\n"
           "**ML / GenAI: Caching hot data for models** (55 min)\n\n"
           "The [chapter](../../course/01-system-design/01-fundamentals.md).\n")
    (weeks / "week-01.md").write_text(day)
    dst = learning_root / "daily"
    dst.mkdir()
    text = course.reading(1, day, weeks, dst, learning_root, course_root)
    # The anchored section, with its sub-section, one level down; the code block is not cut at its '##'.
    assert "### Load Balancers\n\nSpread requests.\n\n#### Algorithms" in text
    assert "### Caching hot data\n\nKeep it near." in text  # the whole-chapter link: its part's topic
    assert "[arrays](../../course/02-dsa/01-arrays.md)" in text  # the quote's own links still work
    assert "[Arrays](../../course/02-dsa/01-arrays.md)" in text  # the chapter no week links
    notes = dst / "notes.md"
    notes.write_text(text)
    assert links.link_problems(notes) == []
    assert course.problems(course_root, learning_root) == []


def test_course_check_finds_broken_anchors_and_pages_the_site_hides(tmp_path):
    from pipeline import course

    course_root, learning_root, weeks = _course(tmp_path)
    (weeks / "week-01.md").write_text("## Day 1: x\n\n[gone](../../course/01-system-design/01-fundamentals.md#gone)\n")
    (course_root / "02-dsa" / "02-hidden.md").write_text("# Hidden\n")
    found = course.problems(course_root, learning_root)
    assert any("02-hidden.md: not in the sidebar" in p for p in found)
    assert any("points at no heading" in p for p in content.week_problems(1, learning_root))
