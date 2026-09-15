FROM ghcr.io/astral-sh/uv:0.12.13@sha256:b485bd65cc2cf1c9a93b3554012c9c3778cf7b1b5fd3d3096ce9e1226c97e1e6 AS uv_binary
FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285
COPY --from=uv_binary /uv /uvx /usr/local/bin/
RUN apt-get update && apt-get install -y --no-install-recommends curl git ripgrep xz-utils ca-certificates procps
ADD hermes-source.tar /opt/hermes/
WORKDIR /opt/hermes
RUN uv sync --frozen --no-dev --python /usr/local/bin/python
ENV PATH="/opt/hermes/.venv/bin:${PATH}"
ENV HERMES_HOME=/tmp/hermes
ENV HERMES_DISABLE_LAZY_INSTALLS=1
COPY skills /tmp/hermes/skills
RUN hermes --version
LABEL org.opencontainers.image.source="https://github.com/NousResearch/hermes-agent"
LABEL org.opencontainers.image.revision="345cd2b057a452236de401d3534b8502a7465e8d"
LABEL org.opencontainers.image.version="0.21.3"
WORKDIR /workspace
