#!/bin/bash
# Starts chromedriver through an Apple-signed shell.
#
# On macOS, Chrome launched straight from chromedriver inside a long-running
# service tree (dashboard -> run -> chromedriver -> Chrome) is denied access to
# a browser profile kept under a protected folder such as Desktop, Documents or
# Downloads. Chrome then shows a "cannot read and write to its data directory"
# dialog and never answers the driver. One /bin/bash hop before chromedriver
# gives Chrome the same file access the user's own shell has.
#
# common/browser.py sets MORROW_CHROMEDRIVER to the real driver path.
if [ -z "$MORROW_CHROMEDRIVER" ]; then
  echo "MORROW_CHROMEDRIVER is not set; this wrapper is started by common/browser.py" >&2
  exit 64
fi
exec "$MORROW_CHROMEDRIVER" "$@"
