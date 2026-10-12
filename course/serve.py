#!/usr/bin/env python3
"""Local server for the course site.

Same as `python3 -m http.server`, but sends `Cache-Control: no-cache` so the
browser always revalidates — edits to .md files show up on a normal refresh,
and stale 404s never get stuck in the browser cache. It always serves the
folder this file is in, so it can be started from any directory.

The job bots live one folder up, in `apply/`, with your passwords, resume and
history. Nothing outside this folder and no dot-file is ever served, and the
server only listens on this computer.

Usage:  python3 serve.py [port]   (default port: 8000)
"""
import functools
import http.server
import os
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
ROOT = os.path.dirname(os.path.abspath(__file__))


def is_private(path):
    """True for anything outside the site: dot-files, or a path leaving ROOT."""
    relative = os.path.relpath(os.path.realpath(path), os.path.realpath(ROOT))
    parts = relative.split(os.sep)
    return parts[0] == '..' or any(p.startswith('.') and p != '.' for p in parts)


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def send_head(self):
        if is_private(self.translate_path(self.path)):
            self.send_error(404, 'File not found')
            return None
        return super().send_head()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()


if __name__ == '__main__':
    handler = functools.partial(NoCacheHandler, directory=ROOT)
    with http.server.ThreadingHTTPServer(('127.0.0.1', PORT), handler) as httpd:
        print(f'Serving course at http://localhost:{PORT}')
        httpd.serve_forever()
