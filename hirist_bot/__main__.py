"""Allows `python3 -m hirist_bot`."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
