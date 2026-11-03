# Animation MCP

![Animation MCP demo](assets/repo_demo.gif)

A Model Context Protocol (MCP) server that lets agents create animations and
drawings with [Manim](https://docs.manim.community) over **streamable HTTP**.

## Example Render

![Math and neural network demo](assets/repo_demo_math_nn.gif)
Created using GLM-5.3-Flash
## Setup

```bash
# System deps (Ubuntu):
sudo apt-get install -y pkg-config libpango1.0-dev libcairo2-dev ffmpeg
pip install -e .
python -m animation_mcp.server   # http://127.0.0.1:8000/mcp
```

Point any streamable-HTTP MCP client at the server URL.

## Tools

| Tool | Purpose |
|---|---|
| `render_manim(code, scene_name, quality, output_format)` | Render a scene; returns artifact paths, download URLs, duration. |
| `get_download_link(job_id, artifact_path, ttl_hours)` | Fresh signed download URL for an artifact. |
| `get_preview(job_id, artifact_path)` | Inline image preview (PNG or MP4 last frame). |
| `get_artifact_base64(job_id, artifact_path)` | Base64 bytes of an artifact (≤ 50 MB). |
| `list_artifacts(job_id)` | All output files of a job. |
| `cleanup_output(older_than_hours)` | Delete old job directories. |

Quality presets: `l` 480p15, `m` 720p30, `h` 1080p60, `p` 1440p60, `k` 2160p60;
`output_format` is `video` (mp4) or `image` (last-frame PNG). Failed renders
return a log tail so the agent can fix and re-render.

## Configuration

All settings are environment variables (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `ANIMATION_MCP_HOST` / `ANIMATION_MCP_PORT` | `127.0.0.1` / `8000` | Bind address. |
| `ANIMATION_MCP_OUTPUT_DIR` | `./output` | Job directory root. |
| `ANIMATION_MCP_PUBLIC_URL` | bind address | Base URL for download links **and** the accepted MCP Host header. Mismatch → `421 Misdirected Request`. |
| `ANIMATION_MCP_ALLOWED_HOSTS` | — | Extra hostnames (comma-separated) accepted by the Host check. |
| `ANIMATION_MCP_TIMEOUT` | `120` | Per-render subprocess timeout (s). |
| `ANIMATION_MCP_MAX_CONCURRENT_RENDERS` | `2` | Simultaneous render cap; extra requests queue briefly. |
| `ANIMATION_MCP_QUEUE_WAIT_SECONDS` | `30` | Queue wait before a "queue full" error. |
| `ANIMATION_MCP_LINK_TTL_HOURS` | `24` | Download-link lifetime (HMAC-signed, up to 720 h). |
| `ANIMATION_MCP_LINK_SECRET` | random per process | Pin for stable links across restarts/replicas. |

Download URLs are signed and expiring:
`http://127.0.0.1:8000/files/<job_id>/<artifact>?expires=...&token=...`
(images render inline via `ImageContent`; video is delivered by download link).

## Docker

```bash
cp .env.example .env   # set ANIMATION_MCP_PUBLIC_URL if needed
sudo docker compose up -d --build
```

Multi-stage build (`python:3.12-slim`) shipping pango/cairo, ffmpeg, and a
LaTeX toolchain so `MathTex`/`Tex` work out of the box; runs as a non-root
`renderer` user with a persistent `mcp-output` volume. ~3 GB image (LaTeX
accounts for most of it).

## Sizing

Each render peaks at ~215 MB (480p15) to ~700 MB (1080p60) RAM; idle server
~70 MB. Guide: 1.5 GB → cap 2, 3 GB → 3–4, 6 GB → 6–8. Uncomment `mem_limit`
in `docker-compose.yml` on small hosts.

## Security

`render_manim` executes arbitrary agent-supplied Python. There is **no sandbox
and no authentication** — bind to localhost unless you add container
isolation, a firewall, and token auth before exposing it remotely.
