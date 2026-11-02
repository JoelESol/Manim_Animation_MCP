"""Unit tests for path containment and helpers (no server required)."""

import asyncio

import pytest

from animation_mcp import config
from animation_mcp.server import _safe_path, _truncate


def test_safe_path_allows_inside_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEFAULT_OUTPUT_DIR", tmp_path)
    # server reads the module attribute at call time via its own reference;
    # patch the name server.py uses
    import animation_mcp.server as server
    monkeypatch.setattr(server, "DEFAULT_OUTPUT_DIR", tmp_path)
    assert _safe_path("job1/media/x.png") == (tmp_path / "job1/media/x.png").resolve()


def test_safe_path_blocks_traversal(tmp_path, monkeypatch):
    import animation_mcp.server as server
    monkeypatch.setattr(server, "DEFAULT_OUTPUT_DIR", tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        _safe_path("../../etc/passwd")
    with pytest.raises(ValueError, match="escapes"):
        _safe_path(str("/etc/passwd"))


def test_truncate_limits_length():
    assert _truncate("x" * 20) == "x" * 20
    out = _truncate("a" * (config.MAX_LOG_CHARS + 10))
    assert len(out) == config.MAX_LOG_CHARS
    assert out.endswith("a")


def test_concurrency_cap_returns_busy_error(tmp_path, monkeypatch):
    import threading

    import animation_mcp.server as server
    from mcp.server.mcpserver.exceptions import ToolError

    monkeypatch.setattr(server, "DEFAULT_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(server, "QUEUE_WAIT_SECONDS", 0.05)
    slots = threading.BoundedSemaphore(1)
    slots.acquire()  # simulate an in-flight render using the only slot
    monkeypatch.setattr(server, "_render_slots", slots)

    with pytest.raises(ToolError, match="queue full"):
        asyncio.run(server.render_manim("from manim import Scene", "Whatever"))


def test_concurrency_cap_releases_slot_after_failure(tmp_path, monkeypatch):
    import threading

    import animation_mcp.server as server
    from mcp.server.mcpserver.exceptions import ToolError

    monkeypatch.setattr(server, "DEFAULT_OUTPUT_DIR", tmp_path)
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(server, "_render_slots", slots)

    # A failing scene must not leak the render slot.
    with pytest.raises(ToolError):
        asyncio.run(server.render_manim("from manim import Scene\nclass B(Scene):\n"
                                        "    def construct(self):\n"
                                        "        self.play(nope)\n", "B"))
    assert slots.acquire(timeout=0), "render slot was not released"
