# The capturer as a container: runs every source once, then exits.
# In Azure it runs with STORAGE=blob and a managed identity, so no secrets are baked in.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY capture/ capture/
COPY certs/ certs/
COPY sources.yaml ./

RUN useradd --create-home --uid 10001 capture
USER capture

ENV PATH=/app/.venv/bin:$PATH \
    STORAGE=blob
ENTRYPOINT ["python", "-m", "capture"]
