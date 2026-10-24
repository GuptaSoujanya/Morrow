"""Small, safe failure summaries for a resumable pipeline checkpoint.

Capture only the current stage's thread. Redirecting stdout/stderr would mix
parallel agents, so isolated bot output explicitly feeds the same collector.
"""

import logging
import os
import re
import threading
from collections import deque
from contextvars import ContextVar
from typing import Optional

MAX_DETAIL = 1200
_current = ContextVar("pipeline_diagnostics", default=None)
_sensitive_name = re.compile(r"password|passwd|secret|token|api[_-]?key|authorization|cookie|credential|signature|session[_-]?id", re.I)
_assignment = re.compile(
    r'''(?i)(["']?(?:[\w.-]*(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|credential|signature|session[_-]?id)[\w.-]*)["']?\s*[:=]\s*)("[^"\n]*"|'[^'\n]*'|[^\s,;&}\]]+)''')


def sanitize_detail(value: object) -> str:
    """Redact credentials before bounding text written to disk or sent to UI.

Known environment values cover bare secrets in third-party exception text;
key/value, URL and token patterns also cover credentials loaded from files.
"""
    text = str(value or "")
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
                  "[redacted private key]", text, flags=re.S)
    for name, secret in sorted(os.environ.items(), key=lambda item: len(item[1]), reverse=True):
        if len(secret) >= 4 and _sensitive_name.search(name):
            text = text.replace(secret, "[redacted]")
    text = re.sub(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", r"\1 [redacted]", text)
    text = re.sub(r"(?i)(https?://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", text)
    text = _assignment.sub(lambda match: match.group(1) + "[redacted]", text)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[redacted]", text)
    text = re.sub(r"\b(?:sk-(?:ant-)?|AIza)[A-Za-z0-9_-]{16,}\b", "[redacted]", text)
    text = "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())
    text = "".join(character for character in text if character == "\n" or ord(character) >= 32)
    return text if len(text) <= MAX_DETAIL else text[:MAX_DETAIL - 1] + "…"


def process_alive(pid: object) -> bool:
    """False only when a recorded process no longer exists (never by age)."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class StageDiagnostics(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.thread_id = threading.get_ident()
        self.errors = deque(maxlen=4)
        self.warnings = deque(maxlen=4)
        self.tail = deque(maxlen=4)
        self.token = None

    def __enter__(self):
        self.token = _current.set(self)
        logging.getLogger().addHandler(self)
        return self

    def __exit__(self, *_):
        logging.getLogger().removeHandler(self)
        _current.reset(self.token)
        self.close()

    def emit(self, record):
        if record.thread == self.thread_id:
            self.add(record.getMessage(), record.levelno)

    def add(self, message: str, level: Optional[int] = None) -> None:
        message = sanitize_detail(message)
        if not message:
            return
        self.tail.append(message)
        if level is None:
            if re.search(r"\b(error|exception|failed|failure|traceback|fatal)\b", message, re.I):
                level = logging.ERROR
            elif re.search(r"\b(warning|warn)\b", message, re.I):
                level = logging.WARNING
        if level is not None and level >= logging.ERROR:
            self.errors.append(message)
        elif level is not None and level >= logging.WARNING:
            self.warnings.append(message)

    def summary(self, code: int) -> str:
        # Last two distinct messages usually retain both cause and corrective
        # instruction without copying an entire CLI response into progress.json.
        messages = list(dict.fromkeys(self.errors or self.warnings or self.tail))[-2:]
        if messages:
            return sanitize_detail("\n".join(messages))
        hint = {1: "Check the required configuration and installed tools.",
                2: "Sign in to this board again, then resume this stage."}.get(
                    code, "Open the run log for details, fix the reported issue, then resume this stage.")
        return "Stage exited with code %s. %s" % (code, hint)


def capture_stage_output(line: str) -> None:
    """Called in the lane's owning thread, without touching global streams."""
    collector = _current.get()
    if collector is not None:
        collector.add(line)
