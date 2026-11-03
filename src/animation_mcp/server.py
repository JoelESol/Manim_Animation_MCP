"""MCP server exposing Manim rendering tools to agents over streamable HTTP.

Tools mirror the surface of reference implementations (execute manim code,
list outputs, fetch artifacts, clean up) but run rendering in a subprocess
with a timeout, validate artifact paths, and serve over streamable-http.

Run:  python -m animation_mcp.server   (or the `animation-mcp` console script)
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver import Image
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from animation_mcp.config import (
    DEFAULT_OUTPUT_DIR,
    HOST,
    LINK_SECRET,
    LINK_TTL_HOURS,
    MAX_CONCURRENT_RENDERS,
    MAX_LOG_CHARS,
    PORT,
    PUBLIC_URL,
    QUEUE_WAIT_SECONDS,
    RENDER_TIMEOUT,
    _host_allowlist,
)

mcp: MCPServer = MCPServer(
    "animation-mcp",
    instructions=(
        "You write Python code for the Manim Community Edition library "
        "(docs: https://docs.manim.community). Submit a complete, standalone "
        "Python module containing a manim.Scene subclass with a construct() "
        "method to render_manim. Workflow: render a draft (quality 'l', or "
        "output_format='image' for fast layout iteration), inspect the "
        "returned preview, fix any errors, then re-render at 'm' or 'h' for "
        "final output. The server has a LaTeX toolchain installed, so "
        "MathTex/Tex work. Every successful render includes download_urls — "
        "share those links with the user so they can open the video/drawing."
    ),
)


class RenderResult(BaseModel):
    job_id: str
    success: bool
    scene_name: str
    output_format: str
    quality: str
    artifacts: list[str] = Field(default_factory=list)
    preview_path: str | None = None
    download_urls: list[str] = Field(default_factory=list)
    duration_seconds: float | None = None


def _sign(job_rel: str, expires: float) -> str:
    """HMAC signature binding an artifact path to an expiry timestamp."""
    msg = f"{job_rel}:{expires:.0f}".encode()
    return hmac.new(LINK_SECRET.encode(), msg, hashlib.sha256).hexdigest()


def make_download_url(job_id: str, rel: str,
                      ttl_hours: float = LINK_TTL_HOURS) -> str:
    """Build a signed, expiring click-to-download URL for an artifact."""
    job_rel = f"{job_id}/{rel}"
    expires = time.time() + ttl_hours * 3600
    token = _sign(job_rel, expires)
    query = urllib.parse.urlencode({"expires": f"{expires:.0f}", "token": token})
    return f"{PUBLIC_URL}/files/{urllib.parse.quote(job_rel)}?{query}"


def verify_download_url(job_id: str, rel: str, token: str,
                        expires: str) -> None:
    """Validate the signature and expiry of a download request."""
    try:
        expires_f = float(expires)
    except (TypeError, ValueError) as exc:
        raise PermissionError("invalid link expiry") from exc
    if expires_f < time.time():
        raise PermissionError("download link has expired; re-render or "
                              "request a fresh link with get_download_link")
    if not hmac.compare_digest(_sign(f"{job_id}/{rel}", expires_f), token or ""):
        raise PermissionError("invalid download link signature")


# Gates how many manim subprocesses run at once. Semaphore acquisition
# happens at call time so tests and env overrides stay simple.
_render_slots = threading.BoundedSemaphore(MAX_CONCURRENT_RENDERS)


def _safe_path(rel: str) -> Path:
    """Resolve a path inside the output dir, refusing traversal."""
    root = DEFAULT_OUTPUT_DIR
    candidate = (root / rel).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"path escapes output directory: {rel}")
    return candidate


def _truncate(text: str) -> str:
    return text[-MAX_LOG_CHARS:] if len(text) > MAX_LOG_CHARS else text


def _last_frame_png(video: Path, job_dir: Path) -> Path | None:
    """Extract the final frame of a rendered video as a preview PNG."""
    png = job_dir / (video.stem + "_preview.png")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-sseof", "-0.1", "-i", str(video),
             "-frames:v", "1", str(png)],
            check=True, capture_output=True, timeout=30,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    return png if png.exists() else None


@mcp.tool()
async def render_manim(
    code: str,
    scene_name: str,
    quality: str = "l",
    output_format: str = "video",
) -> RenderResult:
    """Render a Manim scene from source code.

    Args:
        code: Complete Python source written for the **Manim Community
            Edition** library (docs.manim.community). Import from manim,
            e.g. ``from manim import Scene, Circle``. Define a Scene
            subclass with a construct() method; the server executes the
            module and renders the scene named by scene_name — do not
            instantiate the Scene yourself.
        scene_name: The name of the Scene class to render.
        quality: One of 'l' (480p15, fast draft), 'm' (720p30),
            'h' (1080p60), 'p' (1440p60), 'k' (2160p60).
        output_format: 'video' (mp4) or 'image' (last-frame png).

    Returns:
        RenderResult with artifact paths, an error/log excerpt on failure,
        and the render duration.
    """
    return await asyncio.to_thread(_render_job, code, scene_name, quality,
                                   output_format)


def _render_job(code: str, scene_name: str, quality: str,
                output_format: str) -> RenderResult:
    """Blocking render pipeline; runs on a worker thread."""
    if quality not in {"l", "m", "h", "p", "k"}:
        raise ToolError(f"invalid quality {quality!r}: use l|m|h|p|k")
    if output_format not in {"video", "image"}:
        raise ToolError(f"invalid output_format {output_format!r}: use video|image")

    job_id = uuid.uuid4().hex[:12]
    job_dir = DEFAULT_OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    source = job_dir / "scene.py"
    source.write_text(code, encoding="utf-8")

    # Concurrency cap: wait briefly for a free render slot, then fail fast
    # with a clear message instead of piling up subprocesses (each render
    # needs ~215-700 MB RAM depending on quality).
    if not _render_slots.acquire(timeout=QUEUE_WAIT_SECONDS):
        raise ToolError(
            f"render queue full: {MAX_CONCURRENT_RENDERS} render(s) already "
            f"running and no slot became free within {QUEUE_WAIT_SECONDS:g}s. "
            "Wait a moment and retry, or use a lower quality preset."
        )
    try:
        return _render_scene(job_dir, job_id, scene_name, quality, output_format)
    finally:
        _render_slots.release()


def _render_scene(job_dir: Path, job_id: str, scene_name: str,
                  quality: str, output_format: str) -> RenderResult:
    """Run manim for one scene inside an already-acquired render slot."""
    source = job_dir / "scene.py"

    cmd = [sys.executable, "-m", "manim", f"-q{quality}",
           "--media_dir", str(job_dir / "media")]
    if output_format == "image":
        cmd += ["--format=png", "-s"]
    cmd += [str(source), scene_name]

    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=RENDER_TIMEOUT, cwd=job_dir,
        )
    except subprocess.TimeoutExpired as exc:
        tail = _truncate(((exc.stdout or b"").decode(errors="replace")
                          if isinstance(exc.stdout, bytes) else (exc.stdout or ""))
                         + "\n" + ((exc.stderr or b"").decode(errors="replace")
                                   if isinstance(exc.stderr, bytes) else (exc.stderr or "")))
        raise ToolError(f"render exceeded {RENDER_TIMEOUT}s timeout; log tail:\n{tail}") from exc
    duration = round(time.monotonic() - started, 2)
    log_tail = _truncate(proc.stdout + "\n" + proc.stderr)

    artifacts: list[str] = []
    if proc.returncode == 0:
        pattern = "**/*.png" if output_format == "image" else "**/videos/**/*.mp4"
        candidates = [p for p in job_dir.glob(pattern)
                      if not any("partial" in part for part in p.parts)]
        artifacts = sorted(str(p.relative_to(job_dir)) for p in candidates)
    else:
        raise ToolError(
            f"manim render of {scene_name!r} failed "
            f"({duration}s). Fix the scene and re-render. Log tail:\n{log_tail}"
        )

    preview_path: str | None = None
    download_urls: list[str] = []
    if artifacts:
        first = job_dir / artifacts[0]
        preview = first if first.suffix == ".png" else _last_frame_png(first, job_dir)
        if preview is not None and preview.exists():
            preview_path = str(preview.relative_to(job_dir))
            artifacts.append(preview_path)
        # Clickable download links for the main artifact and preview.
        for rel in (artifacts[0], preview_path):
            if rel:
                download_urls.append(make_download_url(job_id, rel))

    return RenderResult(
        job_id=job_id,
        success=True,
        scene_name=scene_name,
        output_format=output_format,
        quality=quality,
        artifacts=artifacts,
        preview_path=preview_path,
        download_urls=download_urls,
        duration_seconds=duration,
    )


@mcp.tool()
def get_download_link(job_id: str, artifact_path: str,
                      ttl_hours: float = LINK_TTL_HOURS) -> str:
    """Get a fresh, signed, click-to-download URL for an artifact.

    Args:
        job_id: The job that produced the artifact.
        artifact_path: Path as reported in RenderResult.artifacts.
        ttl_hours: How long the link stays valid (default 24).
    """
    if ttl_hours <= 0 or ttl_hours > 24 * 30:
        raise ToolError("ttl_hours must be between 0 and 720")
    path = _safe_path(str(Path(job_id) / artifact_path))
    if not path.is_file():
        raise FileNotFoundError(f"no such artifact: {artifact_path}")
    return make_download_url(job_id, artifact_path, ttl_hours)


@mcp.tool()
def get_preview(job_id: str, artifact_path: str) -> Image:
    """Fetch an output artifact as an inline image preview.

    Args:
        job_id: The job that produced the artifact.
        artifact_path: Path as reported in RenderResult.artifacts.
    """
    path = _safe_path(str(Path(job_id) / artifact_path))
    if not path.is_file():
        raise FileNotFoundError(f"no such artifact: {artifact_path}")
    return Image(path=str(path), format="png" if path.suffix == ".png" else "jpeg")


@mcp.tool()
def get_artifact_base64(job_id: str, artifact_path: str) -> str:
    """Fetch an artifact (e.g. the final .mp4) as base64-encoded bytes."""
    path = _safe_path(str(Path(job_id) / artifact_path))
    if not path.is_file():
        raise FileNotFoundError(f"no such artifact: {artifact_path}")
    data = path.read_bytes()
    if len(data) > 50_000_000:
        raise ValueError("artifact exceeds 50 MB")
    return base64.b64encode(data).decode("ascii")


@mcp.tool()
def list_artifacts(job_id: str) -> list[str]:
    """List every output file produced by a render job."""
    job_dir = _safe_path(job_id)
    if not job_dir.is_dir():
        raise FileNotFoundError(f"no such job: {job_id}")
    files = [p for p in job_dir.rglob("*")
             if p.is_file() and p.suffix != ".py"
             and not any("partial" in part for part in p.parts)]
    return sorted(str(p.relative_to(job_dir)) for p in files)


@mcp.tool()
def cleanup_output(older_than_hours: float = 24) -> int:
    """Delete completed render jobs older than the given age. Returns count."""
    cutoff = time.time() - older_than_hours * 3600
    removed = 0
    if DEFAULT_OUTPUT_DIR.is_dir():
        for job_dir in DEFAULT_OUTPUT_DIR.iterdir():
            if job_dir.is_dir() and job_dir.stat().st_mtime < cutoff:
                shutil.rmtree(job_dir, ignore_errors=True)
                removed += 1
    return removed


def main() -> None:
    """Run the MCP server (streamable HTTP) plus a file-download route."""
    import uvicorn
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator

    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import FileResponse, JSONResponse
    from starlette.routing import Mount, Route

    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    async def download(request: Request) -> FileResponse | JSONResponse:
        job_id = request.path_params["job_id"]
        artifact_path = request.path_params["artifact_path"]
        try:
            verify_download_url(job_id, artifact_path,
                                request.query_params.get("token", ""),
                                request.query_params.get("expires", ""))
            path = _safe_path(str(Path(job_id) / artifact_path))
            if not path.is_file():
                raise FileNotFoundError
        except (PermissionError, ValueError, FileNotFoundError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)
        return FileResponse(
            path,
            media_type=_media_type(path),
            filename=path.name,
            content_disposition_type="attachment",
        )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        # Mounted sub-app lifespans don't run; we own the session manager.
        async with mcp.session_manager.run():
            yield

    app = Starlette(
        routes=[
            # Custom routes must come before the catch-all MCP mount.
            Route("/files/{job_id}/{artifact_path:path}", download,
                  methods=["GET"]),
            Mount("/", app=mcp.streamable_http_app(
                transport_security=_transport_security())),
        ],
        lifespan=lifespan,
    )

    print(f"animation-mcp on {PUBLIC_URL}/mcp (downloads: {PUBLIC_URL}/files/...; "
          f"output dir: {DEFAULT_OUTPUT_DIR})", file=sys.stderr)
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def _transport_security():
    """MCP endpoint Host/Origin allowlist derived from PUBLIC_URL."""
    from mcp.server.transport_security import TransportSecuritySettings

    hosts, origins = _host_allowlist()
    return TransportSecuritySettings(allowed_hosts=hosts,
                                     allowed_origins=origins)


def _media_type(path: Path) -> str:
    return {
        ".png": "image/png",
        ".mp4": "video/mp4",
        ".jpg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")


if __name__ == "__main__":
    main()

