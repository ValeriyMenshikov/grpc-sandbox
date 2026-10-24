"""Healthcheck контейнера gateway: `python -m gateway.healthcheck`, код 0 — /healthz отвечает."""

import os
import sys
import urllib.request

TIMEOUT_S = 2.0


def main() -> int:
    port = os.environ.get("HTTP_PORT", "8080")
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/healthz", timeout=TIMEOUT_S) as reply:
            return 0 if reply.status == 200 else 1
    except OSError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
