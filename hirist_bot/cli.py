"""Apply on Hirist: python3 -m hirist_bot [--limit N] [--dry-run] [--update-profile | --profile-only]."""

import sys
from typing import List, Optional

from sites_bot import platforms

from .board import BOARD


def main(argv: Optional[List[str]] = None) -> int:
    return platforms.main(argv, only=BOARD)


if __name__ == "__main__":
    sys.exit(main())
