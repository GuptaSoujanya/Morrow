"""Conservative evidence for Hirist's renamed resume attachments.

This verifies an upload transaction and its persisted attachment metadata. It
does not claim that the remote PDF bytes have been downloaded or hash-checked.
"""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


_INDIA = timezone(timedelta(hours=5, minutes=30))
_ATTACHMENT = re.compile(
    r"\bAttach Resume\s*\*?\s+([^\n()]{1,160}\.(?:pdf|docx?))\s*"
    r"\(Uploaded On:\s*(\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2})\)"
    r"\s*Upload new resume\s*\|?\s*Download\s*\((\d+\.\d{2}) KB\)", re.I)
_UPLOAD_CODE = re.compile(r"await fileChooser\.setFiles\((\[[^\n]+\])\)")


def _attachment(text):
    matches = set(_ATTACHMENT.findall(" ".join(str(text or "").split())))
    if len(matches) != 1:
        return None
    name, stamp, size = matches.pop()
    try:
        return name, datetime.strptime(stamp, "%d-%m-%Y %H:%M:%S").replace(tzinfo=_INDIA), Decimal(size)
    except (ValueError, ArithmeticError):
        return None


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _successful_upload(transcript, staged, persisted_at):
    calls = {}
    completed = set()
    for line in transcript.splitlines():
        event = json.loads(line)
        if not isinstance(event, dict):
            return False
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        blocks = message.get("content")
        if not isinstance(blocks, list):
            continue
        at = _time(event.get("timestamp"))
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and message.get("role") == "assistant":
                name = block.get("name", "")
                if not isinstance(name, str) or not (name == "browser_file_upload" or name.endswith("__browser_file_upload")):
                    continue
                args = block.get("input")
                identity = block.get("id")
                if (not isinstance(args, dict) or args.get("paths") != [str(staged)]
                        or not isinstance(identity, str) or not identity or identity in calls or at is None):
                    return False
                calls[identity] = at
            elif block.get("type") == "tool_result" and message.get("role") == "user":
                identity = block.get("tool_use_id")
                if not isinstance(identity, str) or identity not in calls:
                    continue
                if (identity in completed or block.get("is_error") or block.get("isError")
                        or at is None or at < calls[identity]):
                    return False
                content = block.get("content")
                if not isinstance(content, list):
                    return False
                texts = [part.get("text", "") for part in content
                         if isinstance(part, dict) and part.get("type") == "text"]
                if not all(isinstance(text, str) for text in texts):
                    return False
                result = "\n".join(texts)
                code = _UPLOAD_CODE.findall(result)
                if ("### Ran Playwright code" not in result or re.search(r"^(?:### Error|Error:)", result, re.M)
                        or len(code) != 1
                        or json.loads(code[0]) != [str(staged)]
                        or not re.search(r"Page URL: https://www\.hirist\.tech/registration/addPersonalDetails(?:\s|$)", result)):
                    return False
                # Hirist displays local India time with second precision. Allow
                # only clock/rounding tolerance around this actual upload call.
                if not calls[identity] - timedelta(seconds=2) <= persisted_at <= at + timedelta(seconds=2):
                    return False
                completed.add(identity)
    # More than one upload in this task is ambiguous; normal repair runs have
    # their own workdir and transcript, and are checked separately.
    return len(calls) == len(completed) == 1


def _staged_resume(folder, expected_name):
    named = folder / expected_name
    if named.is_symlink():
        return None
    if named.is_file():
        return named
    pdfs = [path for path in folder.glob("*.pdf") if not path.is_symlink() and path.is_file()]
    return pdfs[0] if len(pdfs) == 1 else None


def verify_hirist_resume(workdir, expected_name, before_text, after_text, expected_digest=None):
    """Verify the staged resume, a successful upload of it, and saved metadata.

    The staged file is the one named ``expected_name``, or, when no file of that
    name is staged, the single PDF in ``workdir`` (the upload step may have picked
    a tailored PDF under another name). With ``expected_digest`` its sha256 must
    match. ``after_text`` must come from the caller's fresh profile reload.
    Unknown or ambiguous evidence fails closed; agent prose never counts.
    """
    if (not isinstance(expected_name, str) or not expected_name or "\\" in expected_name
            or Path(expected_name).name != expected_name or expected_name in (".", "..")):
        return False
    before, after = _attachment(before_text), _attachment(after_text)
    if before is None or after is None or after[1] <= before[1]:
        return False
    try:
        folder = Path(workdir).resolve(strict=True)
        staged = _staged_resume(folder, expected_name)
        transcript = folder / "transcript.jsonl"
        if staged is None or transcript.is_symlink() or not transcript.is_file():
            return False
        if expected_digest and hashlib.sha256(staged.read_bytes()).hexdigest() != expected_digest:
            return False
        size = staged.stat().st_size
        with staged.open("rb") as handle:
            if not handle.read(1):
                return False
        rounded_size = (Decimal(size) / 1024).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if rounded_size != after[2]:
            return False
        # A staged file modified after the uploaded version is no longer evidence
        # for its current bytes/size, even if its name stayed the same.
        if staged.stat().st_mtime > after[1].timestamp() + 2:
            return False
        return _successful_upload(transcript.read_text(encoding="utf-8"), staged, after[1])
    except (OSError, ValueError, TypeError, ArithmeticError):
        return False
