"""Short, cross-process transactions for files shared by parallel bot runs."""

import fcntl
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Union


@contextmanager
def locked_file(path: Union[str, Path]) -> Iterator[Path]:
    """Lock a stable sidecar, including across atomic replacements of the data file."""
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(target.with_name(".%s.lock" % target.name)),
                         os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield target
    finally:
        os.close(descriptor)


def atomic_write_text(path: Union[str, Path], text: str) -> None:
    """Publish a complete UTF-8 file; callers lock around read/modify/write steps."""
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        mode = 0o600
    descriptor, temporary = tempfile.mkstemp(prefix=".%s-" % target.name, dir=str(target.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
