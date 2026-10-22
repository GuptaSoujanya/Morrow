"""Refresh the Instahyre profile through the browser agent and apply nowhere.

    python3 -m instahyre_bot.update_profile [--dry-run] [--env PATH] [-v]
"""

import sys
from typing import List, Optional

from . import cli


def main(argv: Optional[List[str]] = None) -> int:
    return cli.main(list(sys.argv[1:] if argv is None else argv) + ["--profile-only"])


if __name__ == "__main__":
    sys.exit(main())
