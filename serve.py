"""Serve the repo root over HTTP so the dashboard can read ``data/`` + ``docs/``.

The dashboard (``src/main.html``) fetches ``data/executions/`` and ``docs/`` with
absolute paths from the server root, so it must be served from the repo root;
opening it via ``file://`` is unsupported (D6, dashboard.md).

Usage::

    uv run python serve.py [port]      # default port 8000

then open the printed dashboard URL.
"""

from __future__ import annotations

import http.server
import os
import socketserver
import sys
from pathlib import Path

DEFAULT_PORT = 8000


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    # Always serve from the repo root (this file's directory), regardless of the
    # caller's working directory, so the dashboard's absolute paths resolve.
    os.chdir(Path(__file__).resolve().parent)

    with socketserver.TCPServer(("", port), http.server.SimpleHTTPRequestHandler) as httpd:
        dashboard = f"http://localhost:{port}/src/main.html"
        print(f"Serving repo root at http://localhost:{port}/")
        print(f"Dashboard: {dashboard}")
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
