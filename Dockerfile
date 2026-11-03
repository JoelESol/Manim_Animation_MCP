# animation-mcp server: Manim rendering behind a streamable-HTTP MCP endpoint.
# Multi-stage: build wheels with dev headers, ship a slim runtime.

# ---- build stage ----
FROM python:3.12-slim AS build

# pycairo builds from source, so the build stage needs cairo dev headers
# and pkg-config. manimpango installs from a manylinux wheel.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc pkg-config libcairo2-dev libpango1.0-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# ---- runtime stage ----
FROM python:3.12-slim

# Runtime shared libraries for manim (pango/cairo), ffmpeg for video muxing
# and last-frame preview extraction, and a LaTeX toolchain (with dvisvgm)
# so MathTex/Tex work. texlive-latex-extra brings the standalone class and
# amsmath that manim's default templates require.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangocairo-1.0-0 libcairo2 ffmpeg \
        texlive texlive-latex-extra texlive-fonts-recommended dvisvgm \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY examples ./examples

# Non-root user for the render workload.
RUN useradd --create-home --shell /usr/sbin/nologin renderer \
    && mkdir -p /data/output \
    && chown -R renderer:renderer /app /data
USER renderer

ENV ANIMATION_MCP_OUTPUT_DIR=/data/output \
    ANIMATION_MCP_HOST=0.0.0.0 \
    ANIMATION_MCP_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8000), 4)" || exit 1

CMD ["python", "-m", "animation_mcp.server"]
