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

    state, why = mail.answer(settings, Profile(full_name="Soujanya"), object(), object(), "me@x.com", "pw", lead, False)

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

    state, why = mail.answer(settings, Profile(), object(), object(), "me@x.com", "pw", lead, False)

    assert state == "needs_you" and "notice period" in why
    assert sent == [] and len(drafted) == 1
    assert store.load(settings)[lead["id"]]["state"] == "needs_you"


def test_answer_marks_failed_when_smtp_refuses(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    lead = _recorded(settings)
    _wire(monkeypatch, {"text": "Hi,\n\nYes.", "gaps": []}, send="SMTP refused the mail: 535")

    state, why = mail.answer(settings, Profile(), object(), object(), "me@x.com", "pw", lead, False)

    assert state == "failed" and why.startswith("SMTP refused")
    assert store.load(settings)[lead["id"]]["state"] == "failed"


def test_answer_never_replies_to_assessments_or_board_notifications(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    lead = _recorded(settings)
    sent, drafted = _wire(monkeypatch, {"text": "Hi", "gaps": []})

    state, _ = mail.answer(settings, Profile(), object(), object(), "me@x.com", "pw", dict(lead, kind="ASSESSMENT"), False)
    assert state == "needs_you"
    board = dict(lead, platform="hirist", sender="Hirist <noreply@hirist.tech>")
    state, _ = mail.answer(settings, Profile(), object(), object(), "me@x.com", "pw", board, False)
    assert state == "skipped"
    assert sent == [] and drafted == []
    assert store.load(settings)[lead["id"]]["state"] == "skipped"


def test_answer_dry_run_touches_nothing(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    lead = _recorded(settings)
    sent, drafted = _wire(monkeypatch, {"text": "Hi,\n\nYes.", "gaps": []})

    state, _ = mail.answer(settings, Profile(), object(), object(), "me@x.com", "pw", lead, True)

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

    def fake_answer(settings_, profile, client, im, account, password, lead, dry_run):
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

    assert mail.main(["--no-send", "--days", "3"]) == 0
    assert runs == [("me@x.com", 3, 4, False, False), ("other@x.com", 3, 4, False, False)]


@pytest.mark.parametrize("subject,expected", [("Interview", "Re: Interview"), ("RE: Interview", "RE: Interview")])
def test_compose_threads_and_does_not_double_the_re_prefix(subject, expected):
    from sites_bot.replies import Mail

    their = Mail(message_id="<x@y>", sender="a@b.c", sender_name="A", subject=subject, body="", references="<w@y>")
    message = mail.compose("me@x.com", their, "Hello")
    assert message["Subject"] == expected
    assert message["References"] == "<w@y> <x@y>"
    assert message.get_content().strip() == "Hello"
