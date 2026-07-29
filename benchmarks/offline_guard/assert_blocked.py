"""Assert that the benchmark process cannot open a network connection."""

from __future__ import annotations

import os
import socket

API_KEY_VARIABLES = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")


def main() -> int:
    present = [name for name in API_KEY_VARIABLES if os.environ.get(name)]
    if present:
        raise SystemExit(f"API keys must be absent from the offline job: {', '.join(present)}")
    if os.environ.get("VALIDITY_AUDIT_NETWORK_GUARD") != "active":
        raise SystemExit("Python network guard is not active")
    try:
        socket.create_connection(("example.com", 443))
    except RuntimeError as exc:
        if "network access is disabled" not in str(exc):
            raise
    else:
        raise SystemExit("network guard allowed an outbound connection")
    print("Offline guard PASS: API keys absent and outbound connection blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
