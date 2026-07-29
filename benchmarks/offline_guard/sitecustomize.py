"""Block process-level network access for the offline benchmark CI job."""

from __future__ import annotations

import os
import socket


def _blocked(*args, **kwargs):
    raise RuntimeError("network access is disabled for the golden-case regression job")


socket.create_connection = _blocked
socket.getaddrinfo = _blocked
socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
os.environ["VALIDITY_AUDIT_NETWORK_GUARD"] = "active"
