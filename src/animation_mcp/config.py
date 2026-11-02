"""Runtime configuration for the animation MCP server."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

DEFAULT_OUTPUT_DIR = Path(
    os.environ.get("ANIMATION_MCP_OUTPUT_DIR", "output")
).resolve()

HOST = os.environ.get("ANIMATION_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("ANIMATION_MCP_PORT", "8000"))
RENDER_TIMEOUT = int(os.environ.get("ANIMATION_MCP_TIMEOUT", "120"))
MAX_LOG_CHARS = 8000

# Base URL used in the download links returned to users. Set this to the
# address your browser can reach (e.g. the docker host or a LAN IP); by
# default it matches the server bind address.
PUBLIC_URL = os.environ.get(
    "ANIMATION_MCP_PUBLIC_URL", f"http://{HOST}:{PORT}"
).rstrip("/")

# HMAC secret for signing download links. Auto-generated per process unless
# pinned via env (pin it if you run multiple replicas or restart often).
LINK_SECRET = os.environ.get(
    "ANIMATION_MCP_LINK_SECRET", secrets.token_hex(32)
)
LINK_TTL_HOURS = float(os.environ.get("ANIMATION_MCP_LINK_TTL_HOURS", "24"))


def _host_allowlist() -> tuple[list[str], list[str]]:
    """Host/Origin allowlists for the MCP endpoint's DNS-rebinding check.

    Derived from PUBLIC_URL so that clients reaching the server by its real
    address (e.g. http://134.87.10.114:8000) are accepted, plus the localhost
    variants for local use. Entries are exact: bare host matches the Host
    header without port, host:* matches any port.
    """
    from urllib.parse import urlsplit

    parts = urlsplit(PUBLIC_URL)
    hostname = parts.hostname or "127.0.0.1"
    scheme = parts.scheme or "http"
    extra = [h.strip() for h in
             os.environ.get("ANIMATION_MCP_ALLOWED_HOSTS", "").split(",")
             if h.strip()]

    hosts = {hostname, f"{hostname}:*", "127.0.0.1", "127.0.0.1:*",
             "localhost", "localhost:*", "[::1]", "[::1]:*"}
    hosts.update(extra)
    hosts.update(f"{h}:*" for h in extra)
    origin = f"{scheme}://{hostname}"
    origins = {origin, "http://127.0.0.1", "http://localhost"}
    origins.update(extra)
    return sorted(hosts), sorted(origins)

# Render concurrency: how many manim subprocesses may run simultaneously.
# Extra submissions wait in a queue for up to QUEUE_WAIT_SECONDS before
# getting a busy error. Size these to your RAM: each render peaks at roughly
# 215 MB (480p15 draft) to 700 MB (1080p60).
MAX_CONCURRENT_RENDERS = int(
    os.environ.get("ANIMATION_MCP_MAX_CONCURRENT_RENDERS", "2")
)
QUEUE_WAIT_SECONDS = float(
    os.environ.get("ANIMATION_MCP_QUEUE_WAIT_SECONDS", "30")
)

