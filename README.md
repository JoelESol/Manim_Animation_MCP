# Animation MCP

A Model Context Protocol (MCP) server that lets agents create animations and
drawings with [Manim](https://docs.manim.community) and serve them over
**streamable HTTP** (not stdio).

## Setup

```bash
# System deps (Ubuntu): pkg-config, pango/cairo dev headers, ffmpeg
sudo apt-get install -y pkg-config libpango1.0-dev libcairo2-dev ffmpeg
pip install -e .
```

Run the server:

```bash
python -m animation_mcp.server        # listens on http://127.0.0.1:8000/mcp
```

Environment variables (full table with defaults in the
[Docker section](#environment-variables-all-optional)): `ANIMATION_MCP_HOST`,
`ANIMATION_MCP_PORT`, `ANIMATION_MCP_OUTPUT_DIR`, `ANIMATION_MCP_TIMEOUT`,
`ANIMATION_MCP_MAX_CONCURRENT_RENDERS`, `ANIMATION_MCP_QUEUE_WAIT_SECONDS`,
`ANIMATION_MCP_PUBLIC_URL`, `ANIMATION_MCP_LINK_TTL_HOURS`,
`ANIMATION_MCP_LINK_SECRET`.

## Client configuration

Point any MCP client that speaks streamable HTTP at the server URL, e.g.
`http://127.0.0.1:8000/mcp`. For clients that take a remote-server URL entry,
set the URL to the address above; no command or args are needed.

## Tools

| Tool | Purpose |
|---|---|
| `render_manim(code, scene_name, quality, output_format)` | Render a scene; returns job id, artifact paths, **click-to-download URLs**, duration. Raises `ToolError` with the log tail on failure. |
| `get_download_link(job_id, artifact_path, ttl_hours)` | Fresh signed download URL for any artifact (default 24h validity). |
| `get_preview(job_id, artifact_path)` | Inline image preview of a rendered PNG or the last frame of an MP4. |
| `get_artifact_base64(job_id, artifact_path)` | Base64 bytes of an artifact (e.g. the final MP4). |
| `list_artifacts(job_id)` | All output files of a job (partial movie files excluded). |
| `cleanup_output(older_than_hours)` | Delete old job directories. |

## Security

Rendering agent-supplied Python is arbitrary code execution. The server runs
Manim in a subprocess with a timeout inside a dedicated output directory, and
artifact access is confined to that directory, but there is **no sandbox**.
Only bind to localhost unless you add authentication and container isolation.

## Tests

```bash
# integration test requires the server running:
ANIMATION_MCP_PORT=8737 python -m animation_mcp.server &
# concurrency test: start the server with cap=1, e.g.
#   ANIMATION_MCP_MAX_CONCURRENT_RENDERS=1 ANIMATION_MCP_QUEUE_WAIT_SECONDS=0.1 \
#   ANIMATION_MCP_PORT=8737 python -m animation_mcp.server &
pytest
python tests/test_http_integration.py
python tests/test_concurrency_live.py
```

## Docker

The image is a **multi-stage build** (`python:3.12-slim`): a build stage
compiles `pycairo` with cairo/pango dev headers and gcc; the runtime stage
ships the shared libraries (pango/cairo), **ffmpeg**, and a **LaTeX toolchain**
(`texlive` + `texlive-latex-extra` + `dvisvgm`) so `MathTex`/`Tex` render
out of the box, and runs as a non-root `renderer` user. The image is
~3 GB (LaTeX accounts for most of it).

### Build and run

```bash
# plain docker
sudo docker build -t animation-mcp .
sudo docker run -d --name animation-mcp -p 8000:8000 animation-mcp

# or docker compose (recommended: includes concurrency settings + output volume)
sudo docker compose up -d --build
```

The MCP endpoint is then at `http://127.0.0.1:8000/mcp` — point your MCP
client's remote-server URL there; no command or args are needed.

### Configuration with `.env`

```bash
cp .env.example .env
nano .env        # set ANIMATION_MCP_PUBLIC_URL to the address your client will use
sudo docker compose up -d --build
```

compose reads `.env` automatically and passes the variables into the container.
The single most important value is `ANIMATION_MCP_PUBLIC_URL`: it drives both
the download links and the MCP endpoint's accepted Host — a mismatch shows up
as `421 Misdirected Request` on the client. If you reach the server by several
addresses (public IP, private IP, hostname), set the primary one in
`ANIMATION_MCP_PUBLIC_URL` and add the others to `ANIMATION_MCP_ALLOWED_HOSTS`.

### What compose sets up

From `docker-compose.yml`:

* **Output volume** — rendered artifacts persist in the `mcp-output` named
  volume at `/data/output` in the container. With plain `docker run`, artifacts
  live inside the container unless you add `-v animation-output:/data/output`.
* **Concurrency** — `ANIMATION_MCP_MAX_CONCURRENT_RENDERS=2` and
  `ANIMATION_MCP_QUEUE_WAIT_SECONDS=30` (see [Sizing and concurrency](#sizing-and-concurrency)).
* **Memory limit (optional)** — uncomment `mem_limit: 1500m` for small hosts so
  a runaway render is contained instead of OOM-killing the box.
* **Non-root** — the container runs as the `renderer` user.

### Environment variables (all optional)

| Variable | Default | Notes |
|---|---|---|
| `ANIMATION_MCP_PORT` | `8000` | Port the server binds *inside* the container; use `-p` to map it. |
| `ANIMATION_MCP_HOST` | `127.0.0.1` locally, `0.0.0.0` in the image | Bind address. |
| `ANIMATION_MCP_PUBLIC_URL` | `http://<host>:<port>` | Base URL used in download links. **Set this whenever the browser-facing address differs from the bind address**, e.g. a different published port or a LAN IP. |
| `ANIMATION_MCP_OUTPUT_DIR` | `/data/output` in the image, `./output` locally | Where job directories live. |
| `ANIMATION_MCP_TIMEOUT` | `120` | Per-render subprocess timeout (seconds). |
| `ANIMATION_MCP_MAX_CONCURRENT_RENDERS` | `2` | Simultaneous render cap. |
| `ANIMATION_MCP_QUEUE_WAIT_SECONDS` | `30` | How long a submission waits for a free slot before getting a busy error. |
| `ANIMATION_MCP_LINK_TTL_HOURS` | `24` | Default download-link lifetime. |
| `ANIMATION_MCP_LINK_SECRET` | random per process | Pin it so signed links survive restarts/replicas. |
| `ANIMATION_MCP_ALLOWED_HOSTS` | — | Extra hostnames (comma-separated) accepted by the MCP endpoint's Host check, beyond those derived from `ANIMATION_MCP_PUBLIC_URL`. |

Example: publish on a different port and make download links match:

```bash
sudo docker run -d --name animation-mcp \
  -p 9000:8000 \
  -e ANIMATION_MCP_PUBLIC_URL=http://127.0.0.1:9000 \
  animation-mcp
# MCP endpoint:  http://127.0.0.1:9000/mcp
# Download links: http://127.0.0.1:9000/files/<job_id>/...
```

### Operating the container

```bash
sudo docker ps -f name=animation-mcp        # HEALTHCHECK shows 'healthy'
sudo docker logs -f animation-mcp           # tail server logs
sudo docker compose down                    # stop (keeps the mcp-output volume)
sudo docker cp animation-mcp:/data/output/<job_id>/... .   # grab a file by hand
```

### Verifying the container

```bash
sudo docker compose up -d --build
python tests/test_http_integration.py     # full render/preview/download suite
# concurrency gate (run the container with
# -e ANIMATION_MCP_MAX_CONCURRENT_RENDERS=1 -e ANIMATION_MCP_QUEUE_WAIT_SECONDS=0.1):
python tests/test_concurrency_live.py
```

Both suites were verified passing against the built image.

## Deploying to a remote host

To run on a server (e.g. `134.87.10.114`) and reach it from another machine
(e.g. `134.87.8.213`):

```bash
# on the server (134.87.10.114), as ubuntu:
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2
git clone https://github.com/JoelESol/Animation_MCP.git
cd Animation_MCP

# make download links use the address your other machine will open:
export ANIMATION_MCP_PUBLIC_URL=http://134.87.10.114:8000
sudo -E docker compose up -d --build
```

Two things make remote access work (both are handled by the above):

1. **Bind address** — the Docker image sets `ANIMATION_MCP_HOST=0.0.0.0`, so
   the server accepts connections on all interfaces, not just localhost.
   (`localhost` inside the container is not the same machine as your client.)
2. **Host allowlist** — the MCP SDK's DNS-rebinding protection only accepts
   `localhost` Host headers by default; a client connecting to
   `http://134.87.10.114:8000/mcp` would be rejected with `421 Misdirected
   Request`. The server derives its allowlist from `ANIMATION_MCP_PUBLIC_URL`,
   so setting it to the real address fixes this. Extra hostnames can be
   whitelisted with `ANIMATION_MCP_ALLOWED_HOSTS` (comma-separated).

Then point your MCP client on the other machine at
`http://134.87.10.114:8000/mcp`. Download links will also use that address.

Open the firewall for the client machine only:

```bash
sudo ufw allow from 134.87.8.213 to any port 8000 proto tcp
sudo ufw enable
```

**Security warning:** the MCP endpoint and `/files/` downloads have **no
authentication**, and `render_manim` executes arbitrary Python. Anyone who can
reach port 8000 can run code on the server. Use the firewall rule above (or an
SSH tunnel: `ssh -N -L 8000:localhost:8000 ubuntu@134.87.10.114` from the
client, then `http://localhost:8000/mcp` locally), and do not expose the port
to the internet at large until token auth is added.

To verify from the client machine:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://134.87.10.114:8000/mcp
# 400 = reachable and alive (400 just means 'missing MCP session headers');
# 421 would mean the Host allowlist is wrong.
```

## Click-to-download links

Every successful render returns `download_urls`: signed, expiring URLs like

```
http://127.0.0.1:8000/files/<job_id>/<artifact>?expires=...&token=...
```

Clicking one downloads the file (MP4 or PNG) straight from the device, with
`Content-Disposition: attachment`. Links are HMAC-signed and expire after
`ANIMATION_MCP_LINK_TTL_HOURS` (default 24). Agents can mint fresh links with
`get_download_link` (ttl up to 30 days).

The base URL in the links comes from `ANIMATION_MCP_PUBLIC_URL` — see the
[environment variable table](#environment-variables-all-optional) in the Docker
section; the same variable applies to non-Docker runs.

## Sizing and concurrency

* `ANIMATION_MCP_MAX_CONCURRENT_RENDERS` — how many renders may run at the
  same time (default 2). Additional submissions wait in a short queue; if no
  slot frees within `ANIMATION_MCP_QUEUE_WAIT_SECONDS` (default 30), the agent
  gets a clear "queue full, retry" error instead of a hang.
* Memory per render (measured): ~215 MB at 480p15, ~320 MB at 720p30,
  ~700 MB at 1080p60. The idle server adds ~70 MB. So:
  * 1 vCPU / 1.5 GB: cap at 2 for drafts, 1 for high quality.
  * 2 vCPU / 3 GB: cap at 3–4 (recommended tier).
  * 4 vCPU / 6 GB: cap at 6–8.
* `ANIMATION_MCP_TIMEOUT` — per-render subprocess timeout in seconds (120).
* In compose, uncomment `mem_limit` on small hosts to contain runaway renders.

Note: the `/files/...` route is plain HTTP served by this app, so it is not
affected by the MCP transport's DNS-rebinding allowlist; but keep the server
off the public internet unless you add authentication.

## Can the client see output inline in chat?

* **Images** — yes. `render_manim` and `get_preview` return real
  `ImageContent` blocks, so any MCP client that renders images (Claude
  Desktop/Code, VS Code Copilot agent mode, etc.) shows the drawing or the
  video's final frame directly in the chat.
* **Video** — not inline. MCP has no video content block, but every render
  result includes `download_urls` — one click downloads the MP4 from the
  server (see [Click-to-download links](#click-to-download-links)). Agents can
  also fetch bytes via `get_artifact_base64` and save the file locally.
* When `output_format="image"` the render itself is a PNG, which is always
  viewable inline — the most reliable option for chat-only workflows.

