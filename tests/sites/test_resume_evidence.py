import json
import os
from datetime import datetime

import pytest

from sites_bot.resume_evidence import verify_hirist_resume


BEFORE = "Attach Resume* candidate.pdf (Uploaded On: 03-11-2026 12:17:44) Upload new resume | Download (81.29 KB)"
AFTER = "Attach Resume* candidate.pdf (Uploaded On: 03-11-2026 17:33:08) Upload new resume | Download (81.29 KB)"


def _events(path):
    paths = [str(path)]
    return [
        {"timestamp": "2026-11-03T12:03:08.579Z", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "upload-1", "name": "mcp__browser__browser_file_upload", "input": {"paths": paths}}]}},
        {"timestamp": "2026-11-03T12:03:14.746Z", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "upload-1", "content": [{"type": "text", "text":
                '### Ran Playwright code\n```js\nawait fileChooser.setFiles(' + json.dumps(paths) + ')\n```\n'
                '### Page\n- Page URL: https://www.hirist.tech/registration/addPersonalDetails\n'
                '- Page Title: Complete your profile\n### Snapshot\n- [Snapshot](./page.yml)'}]}]}}
    ]


def _write(folder, events):
    (folder / "transcript.jsonl").write_text("\n".join(json.dumps(event) for event in events))


@pytest.fixture
def upload(tmp_path):
    path = tmp_path / "onboarding.pdf"
    path.write_bytes(b"%PDF-" + b"x" * (83237 - 5))
    staged_at = datetime.fromisoformat("2026-11-03T12:02:00+00:00").timestamp()
    os.utime(path, (staged_at, staged_at))
    events = _events(path)
    _write(tmp_path, events)
    return tmp_path, path, events


def test_hirist_rename_is_verified_by_successful_upload_and_persisted_metadata(upload):
    folder, path, _ = upload
    assert verify_hirist_resume(folder, path.name, BEFORE, AFTER)


def test_profile_check_uses_upload_evidence_only_for_hirist_resume(upload):
    from sites_bot import profile_agent
    from hirist_bot.board import BOARD as HIRIST
    from cutshort_bot.board import BOARD as CUTSHORT

    folder, path, _ = upload
    (folder / 'before.txt').write_text(BEFORE)
    section = profile_agent.Section('Resume', 'updated', target=path.name)
    assert profile_agent._confirm_saved(section, AFTER, HIRIST, folder) == (True, [])
    assert 'changed upload time and matching size' in section.note
    assert profile_agent._confirm_saved(section, AFTER, CUTSHORT, folder)[0] is not True
    assert profile_agent._confirm_saved(section, BEFORE, HIRIST, folder)[0] is not True


def test_repair_check_keeps_renamed_resume_verification(upload):
    import shutil
    from sites_bot import profile_agent
    from hirist_bot.board import BOARD

    folder, path, _ = upload
    (folder / 'page-after.txt').write_text(BEFORE)
    repair = folder / 'repair-1'
    repair.mkdir()
    staged = repair / path.name
    shutil.copy2(path, staged)
    _write(repair, _events(staged))
    section = profile_agent.Section('Resume', 'updated', target=path.name)
    assert profile_agent._confirm_saved(section, AFTER, BOARD, repair) == (True, [])


def test_unrelated_repair_keeps_original_resume_evidence_only_for_unchanged_attachment(upload):
    from sites_bot import profile_agent
    from hirist_bot.board import BOARD

    folder, path, _ = upload
    (folder / 'before.txt').write_text(BEFORE)
    (folder / 'page-after.txt').write_text(AFTER)
    repair = folder / 'repair-1'
    repair.mkdir()
    (repair / 'transcript.jsonl').write_text('')
    section = profile_agent.Section('Resume', 'updated', target=path.name)
    assert profile_agent._confirm_saved(section, AFTER, BOARD, repair) == (True, [])
    changed = AFTER.replace('17:33:08', '17:35:08')
    assert profile_agent._confirm_saved(section, changed, BOARD, repair)[0] is not True


@pytest.mark.parametrize("before,after", [
    (AFTER, AFTER),
    (AFTER, BEFORE),
    ("Resume attached", AFTER),
    (BEFORE, "Resume uploaded successfully"),
    (BEFORE, AFTER.replace("81.29", "81.30")),
    (BEFORE, AFTER.replace("81.29 KB", "0.08 MB")),
    (BEFORE, AFTER.replace("03-11-2026", "2026-11-03")),
    (BEFORE, AFTER.replace("17:33:08", "17:34:08")),
    (BEFORE, AFTER + " " + AFTER.replace("candidate.pdf", "other.pdf")),
])
def test_missing_unchanged_or_ambiguous_saved_metadata_is_not_proof(upload, before, after):
    folder, path, _ = upload
    assert not verify_hirist_resume(folder, path.name, before, after)


@pytest.mark.parametrize("change", ["missing_result", "error", "wrong_id", "wrong_path", "other_folder",
                                     "agent_assertion", "no_success_code", "wrong_site", "bad_time", "duplicate", "error_text"])
def test_only_successful_exact_current_task_upload_tool_evidence_counts(upload, change):
    folder, path, events = upload
    call = events[0]["message"]["content"][0]
    result = events[1]["message"]["content"][0]
    if change == "missing_result":
        events.pop()
    elif change == "error":
        result["is_error"] = True
    elif change == "error_text":
        result["content"][0]["text"] += "\n### Error\nUpload failed"
    elif change == "wrong_id":
        result["tool_use_id"] = "other-upload"
    elif change == "wrong_path":
        call["input"]["paths"] = [str(folder / "other.pdf")]
    elif change == "other_folder":
        events = _events(folder.parent / path.name)
    elif change == "agent_assertion":
        events[1]["message"]["role"] = "assistant"
    elif change == "no_success_code":
        result["content"][0]["text"] = "The agent says it uploaded onboarding.pdf successfully"
    elif change == "wrong_site":
        result["content"][0]["text"] = result["content"][0]["text"].replace("www.hirist.tech", "www.hirist.tech.evil.test")
    elif change == "bad_time":
        events[1]["timestamp"] = "no timestamp"
    elif change == "duplicate":
        events.append(events[0])
    _write(folder, events)
    assert not verify_hirist_resume(folder, path.name, BEFORE, AFTER)


@pytest.mark.parametrize("name", ["../onboarding.pdf", "/tmp/onboarding.pdf", "folder/onboarding.pdf", "folder\\onboarding.pdf", ""])
def test_expected_name_cannot_choose_a_file_outside_current_task(upload, name):
    folder, _, _ = upload
    assert not verify_hirist_resume(folder, name, BEFORE, AFTER)


def test_changed_staged_file_cannot_verify_the_earlier_upload(upload):
    folder, path, _ = upload
    later = datetime.fromisoformat("2026-11-03T12:04:00+00:00").timestamp()
    os.utime(path, (later, later))
    assert not verify_hirist_resume(folder, path.name, BEFORE, AFTER)


def test_malformed_transcript_is_not_partial_success(upload):
    folder, path, _ = upload
    with (folder / "transcript.jsonl").open("a") as handle:
        handle.write("\n{broken")
    assert not verify_hirist_resume(folder, path.name, BEFORE, AFTER)


def test_missing_file_and_symlink_are_not_staged_evidence(upload):
    folder, path, events = upload
    target = folder / "actual.pdf"
    path.rename(target)
    assert not verify_hirist_resume(folder, path.name, BEFORE, AFTER)
    path.symlink_to(target)
    assert not verify_hirist_resume(folder, path.name, BEFORE, AFTER)


def test_unknown_transcript_shapes_fail_without_raising(upload):
    folder, path, _ = upload
    _write(folder, [{"message": {"role": "user", "content": "not tool results"}}])
    assert not verify_hirist_resume(folder, path.name, BEFORE, AFTER)
