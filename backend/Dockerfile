FROM python:3.13-slim

# Pinned by tag + digest so builds are reproducible; Dependabot proposes updates.
COPY --from=ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85 /uv /bin/uv
WORKDIR /app

# "--extra local" adds FastEmbed (local multilingual models). Build with
# --build-arg UV_EXTRAS="" for a slim image that only has the hash/OpenAI providers.
ARG UV_EXTRAS="--extra local"
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project ${UV_EXTRAS}

COPY app ./app

# Run unprivileged; /data must exist and be owned before VOLUME so a fresh
# named volume inherits the ownership.
RUN useradd --system --uid 10001 --home-dir /app app \
    && mkdir -p /data \
    && chown -R app:app /data
USER app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    SIM_DATA_DIR=/data \
    FASTEMBED_CACHE_PATH=/data/models
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
