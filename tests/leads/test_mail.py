from pathlib import Path

import pytest

from common.models import Profile, Settings
from leads import mail, store


def _settings(tmp_path, **over):
    values = dict(data_dir=str(tmp_path / "inputs"), report_dir=str(tmp_path / "reports"), leads_auto_reply=True)
    values.update(over)
    return Settings(**values)


def _lead(subject="Interview invitation", key="k1", **over):
    lead = store.make_lead("mail", "employer", "INTERVIEW", company="Acme", who="HR", subject=subject, key=key)
    lead["sender"] = "HR <careers@acme.com>"
    lead["folder"] = "[Gmail]/All Mail"
    lead.update(over)
    return lead


def test_decide_covers_every_outcome():
    lead = {"kind": "REPLY", "platform": "employer", "folder": "[Gmail]/Spam"}
    assert mail.decide(dict(lead, kind="ASSESSMENT"), False, {"text": "x"})[0] == "needs_you"
    assert mail.decide(dict(lead, platform="naukri"), False, {"text": "x"}) == (
        "skipped", "A naukri notification; the board's own inbox stage (inbox:naukri) answers it on the board.")
    assert mail.decide(lead, True, {"text": "x"})[0] == "skipped"
    assert mail.decide(lead, False, None)[0] == "failed"
    assert mail.decide(lead, False, {"text": "", "gaps": []})[0] == "failed"
    state, why = mail.decide(lead, False, {"text": "Hi […]", "gaps": ["notice period"]})
    assert state == "needs_you" and "notice period" in why
    assert mail.decide(lead, False, {"text": "Hi", "gaps": []}, auto_reply=False)[0] == "needs_you"
    assert mail.decide(lead, False, {"text": "Hi", "gaps": []}) == ("answered", "Replied from the saved facts.")


def test_read_leads_keeps_positive_mail_once_with_its_imap_handle(monkeypatch):
    acme = {"from": "HR <careers@acme.com>", "subject": "Interview invitation - AI Engineer",
            "date": "Tue, 11 Nov 2026 09:00:00 +0530", "message_id": "<a@acme>", "bulk": False}
    alert = {"from": "Naukri <info@naukri.com>", "subject": "Recruiter message", "date": "Tue, 11 Nov 2026 08:00:00 +0530",
             "message_id": "<n@naukri>", "bulk": True}
    folders = {"[Gmail]/All Mail": [(b"11", acme), (b"12", alert)], "[Gmail]/Spam": [(b"3", acme)]}
    rows = {uid: header for items in folders.values() for uid, header in items}
    monkeypatch.setattr(mail.gmail, "_uids", lambda imap, folder, since: [uid for uid, _ in folders[folder]])
    monkeypatch.setattr(mail.gmail, "_fetch_headers", lambda imap, uids: [(uid, rows[uid]) for uid in uids])

    leads = mail.read_leads(object(), 2)

    assert [lead["kind"] for lead in leads] == ["INTERVIEW"]
    assert leads[0]["_uid"] == b"11" and leads[0]["_folder"] == "[Gmail]/All Mail"
    assert leads[0]["_header"]["message_id"] == "<a@acme>"
    assert leads[0]["sender"] == "HR <careers@acme.com>"
    assert "_uid" not in mail._public(leads[0])


def _wire(monkeypatch, draft, send=""):
    from sites_bot import replies

    monkeypatch.setattr(mail.gmail, "_select", lambda imap, folder: True)
    monkeypatch.setattr(mail.gmail, "_fetch_body", lambda imap, uid: "Can you join Tuesday at 3pm?")
    monkeypatch.setattr(replies, "classify", lambda client, m, app: {"kind": "INTERVIEW", "questions": ["Tuesday 3pm?"]})
    monkeypatch.setattr(replies, "draft_reply", lambda client, p, m, app, found: draft)
    monkeypatch.setattr(mail, "_facts", lambda p, s: "abc")
    sent, drafted = [], []
    monkeypatch.setattr(mail, "send_message", lambda account, pw, msg: sent.append(msg) or send)
    monkeypatch.setattr(mail, "save_draft", lambda settings, account, pw, msg: drafted.append(msg) or "")
    return sent, drafted


def _imap(settings):
    return mail.imap_transport(object(), "me@x.com", "pw", settings)


def _recorded(settings):
    lead = _lead()
    store.record(settings, [lead])
    lead.update(_uid=b"11", _folder="[Gmail]/All Mail",
                _header={"message_id": "<a@acme>", "from": "HR <careers@acme.com>"})
    return lead


def test_answer_sends_a_complete_draft_threaded_under_their_mail(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    lead = _recorded(settings)
    sent, drafted = _wire(monkeypatch, {"text": "Hi,\n\nTuesday 3pm works.\n\nBest regards,\nSoujanya", "gaps": []})

    state, why = mail.answer(settings, Profile(full_name="Soujanya"), object(), _imap(settings), lead, False)

    assert (state, why) == ("answered", "Replied from the saved facts.")
    assert drafted == [] and len(sent) == 1
    assert sent[0]["To"] == "careers@acme.com"
    assert sent[0]["Subject"] == "Re: Interview invitation"
    assert sent[0]["In-Reply-To"] == "<a@acme>"
    saved = store.load(settings)[lead["id"]]
    assert saved["state"] == "answered" and saved["facts"] == "abc" and "Tuesday 3pm" in saved["answer"]
    kept = Path(saved["answer_file"])
    assert kept.parent == mail.answers_dir(settings) and "STATE: answered" in kept.read_text()


def test_answer_with_gaps_leaves_a_gmail_draft_and_waits_on_you(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    lead = _recorded(settings)
    sent, drafted = _wire(monkeypatch, {"text": "Hi,\n\nMy notice is […].", "gaps": ["notice period"]})

    state, why = mail.answer(settings, Profile(), object(), _imap(settings), lead, False)

    assert state == "needs_you" and "notice period" in why
    assert sent == [] and len(drafted) == 1
    assert store.load(settings)[lead["id"]]["state"] == "needs_you"


def test_answer_falls_back_to_a_draft_when_sending_fails(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    lead = _recorded(settings)
    sent, drafted = _wire(monkeypatch, {"text": "Hi,\n\nYes.", "gaps": []}, send="SMTP refused the mail: 535")

    state, why = mail.answer(settings, Profile(), object(), _imap(settings), lead, False)

    assert state == "needs_you" and "SMTP refused" in why and "Gmail Drafts" in why
    assert len(sent) == 1 and len(drafted) == 1
    saved = store.load(settings)[lead["id"]]
    assert saved["state"] == "needs_you" and saved["via"] == "imap"


def test_answer_never_replies_to_assessments_or_board_notifications(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    lead = _recorded(settings)
    sent, drafted = _wire(monkeypatch, {"text": "Hi", "gaps": []})

    state, _ = mail.answer(settings, Profile(), object(), _imap(settings), dict(lead, kind="ASSESSMENT"), False)
    assert state == "needs_you"
    board = dict(lead, platform="hirist", sender="Hirist <noreply@hirist.tech>")
    state, _ = mail.answer(settings, Profile(), object(), _imap(settings), board, False)
    assert state == "skipped"
    assert sent == [] and drafted == []
    assert store.load(settings)[lead["id"]]["state"] == "skipped"


def test_answer_dry_run_touches_nothing(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    lead = _recorded(settings)
    sent, drafted = _wire(monkeypatch, {"text": "Hi,\n\nYes.", "gaps": []})

    state, _ = mail.answer(settings, Profile(), object(), _imap(settings), lead, True)

    assert state == "answered" and sent == [] and drafted == []
    assert store.load(settings)[lead["id"]]["state"] == "new"
    assert not mail.answers_dir(settings).exists()


class _Imap:
    def __init__(self):
        self.closed = False

    def logout(self):
        self.closed = True


def test_run_inbox_records_claims_and_honours_the_limit(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    leads = [_lead(subject="Interview %d" % n, key="k%d" % n) for n in range(3)]
    for lead in leads:
        lead.update(_uid=b"1", _folder="[Gmail]/All Mail", _header={"message_id": "<%s>" % lead["id"]})
    imap = _Imap()
    monkeypatch.setattr(mail.gmail, "_connect", lambda account, password: imap)
    monkeypatch.setattr(mail, "read_leads", lambda im, days: leads)
    monkeypatch.setattr(mail, "_facts", lambda p, s: "abc")
    answered = []

    def fake_answer(settings_, profile, client, transport, lead, dry_run):
        answered.append(lead["id"])
        store.update(settings_, lead["id"], "answered", "ok", facts="abc")
        return "answered", "ok"

    monkeypatch.setattr(mail, "answer", fake_answer)

    counts = mail.run_inbox(settings, Profile(), None, "me@x.com", "pw", 2, 2, False)

    assert counts["scanned"] == 3 and counts["new"] == 3 and counts["answered"] == 2
    assert len(answered) == 2 and imap.closed
    states = sorted(lead["state"] for lead in store.load(settings).values())
    assert states == ["answered", "answered", "new"]

    counts = mail.run_inbox(settings, Profile(), None, "me@x.com", "pw", 2, 5, False)
    assert counts["answered"] == 1 and len(answered) == 3


def test_run_inbox_without_a_password_or_dry_run_writes_nothing(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    assert mail.run_inbox(settings, Profile(), None, "me@x.com", "", 2, 5, False)["scanned"] == 0
    monkeypatch.setattr(mail.gmail, "_connect", lambda account, password: _Imap())
    monkeypatch.setattr(mail, "read_leads", lambda im, days: [_lead()])
    monkeypatch.setattr(mail, "answer", lambda *args: ("answered", "ok"))

    counts = mail.run_inbox(settings, Profile(), None, "me@x.com", "pw", 2, 5, True)

    assert counts["scanned"] == 1 and counts["answered"] == 1
    assert not store.path(settings).exists()


def test_main_runs_each_inbox_and_no_send_turns_auto_reply_off(monkeypatch, tmp_path):
    from common import config, profile as profile_module, report
    from sites_bot import accounts, replies

    monkeypatch.setattr(config, "load_settings", lambda env=None, overrides=None: _settings(tmp_path, leads_limit=4))
    monkeypatch.setattr(profile_module, "load_profile", lambda settings: Profile(full_name="S"))
    monkeypatch.setattr(accounts, "account_email", lambda settings: "me@x.com")
    monkeypatch.setattr(replies, "inboxes", lambda settings, account: [("me@x.com", "pw"), ("other@x.com", "pw2")])
    monkeypatch.setattr(report, "update_quietly", lambda settings: None)
    runs = []
    monkeypatch.setattr(mail, "run_inbox", lambda settings, profile, client, account, pw, days, limit, dry:
                        runs.append((account, days, limit, dry, settings.leads_auto_reply)) or {"scanned": 1})
    monkeypatch.setattr(mail, "run_browser", lambda *args: pytest.fail("passwords exist; no browser read expected"))

    assert mail.main(["--no-send", "--days", "3"]) == 0
    assert runs == [("me@x.com", 3, 4, False, False), ("other@x.com", 3, 4, False, False)]


def test_main_reads_through_the_browser_when_no_inbox_has_a_password(monkeypatch, tmp_path):
    from common import config, profile as profile_module, report
    from sites_bot import accounts, replies

    monkeypatch.setattr(config, "load_settings", lambda env=None, overrides=None: _settings(tmp_path))
    monkeypatch.setattr(profile_module, "load_profile", lambda settings: Profile())
    monkeypatch.setattr(accounts, "account_email", lambda settings: "me@x.com")
    monkeypatch.setattr(replies, "inboxes", lambda settings, account: [("me@x.com", ""), ("other@x.com", "")])
    monkeypatch.setattr(report, "update_quietly", lambda settings: None)
    monkeypatch.setattr(mail, "run_inbox", lambda *args: pytest.fail("no password, so no IMAP read"))
    seen = []
    monkeypatch.setattr(mail, "run_browser", lambda settings, profile, client, days, limit, dry:
                        seen.append((days, limit, dry)) or {"scanned": 2})

    assert mail.main(["--dry-run"]) == 0
    assert seen == [(mail.FIRST_RUN_DAYS, 10, True)], "an empty journal reads further back once"
    store.record(_settings(tmp_path), [_lead()])
    assert mail.main(["--dry-run"]) == 0
    assert seen[-1] == (2, 10, True)


@pytest.mark.parametrize("subject,expected", [("Interview", "Re: Interview"), ("RE: Interview", "RE: Interview")])
def test_compose_threads_and_does_not_double_the_re_prefix(subject, expected):
    from sites_bot.replies import Mail

    their = Mail(message_id="<x@y>", sender="a@b.c", sender_name="A", subject=subject, body="", references="<w@y>")
    message = mail.compose("me@x.com", their, "Hello")
    assert message["Subject"] == expected
    assert message["References"] == "<w@y> <x@y>"
    assert message.get_content().strip() == "Hello"


class _Driver:
    def __init__(self, url="https://mail.google.com/mail/u/0/#inbox", body="Can you join Tuesday at 3pm?"):
        self.current_url = url
        self.body = body
        self.visited = []
        self.window_handles = ["h1"]

    def get(self, url):
        self.visited.append(url)

    def execute_script(self, script, *args):
        if script == mail.gmail_browser._OPEN:
            return True
        if script == mail.gmail_browser._BODY:
            return self.body
        if script == mail.gmail_browser._ACCOUNT:
            return "me@x.com"
        return []

    def quit(self):
        pass


def test_read_browser_leads_uses_gmails_search_pages(monkeypatch):
    rows = {"newer_than:2d": [{"from": "careers@acme.com", "name": "HR", "subject": "Interview invitation - AI Engineer",
                              "date": "Nov 11"},
                             {"from": "info@naukri.com", "name": "Naukri", "subject": "Recruiter message", "date": "Nov 10"}],
            "in:spam newer_than:2d": [{"from": "careers@acme.com", "name": "HR",
                                       "subject": "Interview invitation - AI Engineer", "date": "Nov 11"}]}
    monkeypatch.setattr(mail.gmail_browser, "_rows_for", lambda driver, query: rows[query])
    monkeypatch.setattr(mail.time, "sleep", lambda s: None)

    leads = mail.read_browser_leads(_Driver(), 2)

    assert [lead["kind"] for lead in leads] == ["INTERVIEW"] and leads[0]["sender"] == "HR <careers@acme.com>"
    assert mail.browser_body(_Driver(), leads[0]) == "Can you join Tuesday at 3pm?"


def test_browser_send_is_only_done_when_the_reply_is_visible(monkeypatch, tmp_path):
    from sites_bot import browser_agent
    from sites_bot.replies import Mail

    settings = _settings(tmp_path, browser_agent=True, browser_agent_limit=3)
    monkeypatch.setattr(mail.time, "sleep", lambda s: None)
    monkeypatch.setattr(browser_agent, "reserve_task", lambda settings: True)
    monkeypatch.setattr(browser_agent, "task_prompt", lambda *a, **k: "PROMPT")
    monkeypatch.setattr(browser_agent, "workdir_for", lambda settings, label: tmp_path / "work")
    reports = iter([{"status": "done"}, {"status": "done"}, {"status": "needs_you", "why": "A captcha appeared"}])
    monkeypatch.setattr(browser_agent, "run_agent", lambda driver, settings, prompt, wd:
                        browser_agent.AgentRun(report=next(reports), workdir=wd, seconds=1.0))
    visible = iter([True, False])
    monkeypatch.setattr(mail, "_reply_visible", lambda driver, text: next(visible))
    their = Mail(message_id="gmail:1", sender="careers@acme.com", sender_name="HR", subject="Interview", body="")

    assert mail.browser_send(_Driver(), settings, Profile(), their, "Hi,\n\nTuesday 3pm works for me.\n\nBest") == ""
    assert "not visible" in mail.browser_send(_Driver(), settings, Profile(), their, "Hi,\n\nTuesday 3pm works for me.")
    assert mail.browser_send(_Driver(), settings, Profile(), their, "Hi") == "A captcha appeared"
    monkeypatch.setattr(browser_agent, "reserve_task", lambda settings: False)
    assert "no browser-agent task" in mail.browser_send(_Driver(), settings, Profile(), their, "Hi")


def test_run_browser_uses_the_first_signed_in_profile(monkeypatch, tmp_path):
    from common import connections

    settings = _settings(tmp_path)
    (tmp_path / "naukri").mkdir()
    (tmp_path / "linkedin").mkdir()
    monkeypatch.setattr(mail.gmail_browser, "candidate_profiles",
                        lambda settings: [("naukri", tmp_path / "naukri"), ("linkedin", tmp_path / "linkedin")])
    drivers = {str(tmp_path / "naukri"): _Driver(url="https://accounts.google.com/signin"),
               str(tmp_path / "linkedin"): _Driver()}
    monkeypatch.setattr(connections, "create_driver", lambda s: drivers[s.browser_profile_dir])
    monkeypatch.setattr(mail.time, "sleep", lambda s: None)
    monkeypatch.setattr(mail, "read_browser_leads", lambda driver, days: [_lead()])
    seen = []

    def fake_answer_waiting(settings_, profile, client, transport, leads, limit, dry_run):
        seen.append((transport.via, transport.account, len(leads), limit, dry_run))
        return {"scanned": len(leads)}

    monkeypatch.setattr(mail, "answer_waiting", fake_answer_waiting)

    assert mail.run_browser(settings, Profile(), None, 2, 5, False) == {"scanned": 1}
    assert seen == [("browser", "me@x.com", 1, 5, False)]


class _Tabs:
    """Two tabs: a board page and the Gmail thread; switch_to.window changes what the scripts see."""

    def __init__(self, thread_text):
        self.window_handles = ["board", "gmail"]
        self.current_window_handle = "board"
        self.current_url = "https://www.hirist.tech/chats"
        self.thread_text = thread_text
        self.switch_to = self

    def window(self, handle):
        self.current_window_handle = handle
        self.current_url = "https://mail.google.com/mail/u/0/#search/x" if handle == "gmail" else "https://www.hirist.tech/chats"

    def execute_script(self, script, *args):
        assert "mail.google.com" in self.current_url, "the thread is read on the Gmail tab only"
        return self.thread_text


def test_reply_visible_reads_the_gmail_tab_and_comes_back():
    reply = "Hi Anna,\n\nTuesday at 3 pm works for me; I will join from Gurugram.\n\nBest regards,\nSoujanya"
    tabs = _Tabs("Their mail\nTuesday at 3 pm works for me; I will join from Gurugram.\nMessage sent")
    assert mail._reply_visible(tabs, reply) is True
    assert tabs.current_window_handle == "board"
    assert mail._reply_visible(_Tabs("Their mail only"), reply) is False
    assert mail._reply_visible(_Tabs("Hi"), "Hi") is False


def test_first_run_days_reads_further_back_until_a_mail_lead_exists(tmp_path):
    settings = _settings(tmp_path)
    assert mail.first_run_days(settings, 2) == mail.FIRST_RUN_DAYS
    store.record(settings, [store.make_lead("board", "hirist", "REPLY", who="Asha", key="b1")])
    assert mail.first_run_days(settings, 2) == mail.FIRST_RUN_DAYS, "board leads alone do not count"
    store.record(settings, [_lead()])
    assert mail.first_run_days(settings, 2) == 2
    assert mail.first_run_days(settings, 45) == 45
