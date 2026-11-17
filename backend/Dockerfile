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

# The app runs as UID/GID 10001. /data is owned before VOLUME so a fresh named
# volume inherits the ownership.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app app \
    && mkdir -p /data \
    && chown -R app:app /data
# No USER here on purpose: a platform volume mounted on /data usually belongs to
# root, so the entrypoint starts as root, gives /data to 10001 and then drops
# root (setpriv) before the app runs. docker-compose starts it as 10001 directly.
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# The root filesystem is read-only in compose: every cache lives on /data.
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    SIM_DATA_DIR=/data \
    FASTEMBED_CACHE_PATH=/data/models \
    HF_HOME=/data/huggingface
VOLUME /data
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
# --no-server-header: do not advertise the server software.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
