# Similarityly · همسان‌یاب

Find duplicate and near-duplicate text across your data. Load spreadsheets,
documents or pasted lists into **repositories**; every new record is scored
against everything indexed before it and labelled *duplicate*, *similar* or
*unique*. Built with first-class Persian support (character unification,
digit normalization, ZWNJ handling, RTL UI) and works just as well for English.

- **Inputs:** Excel (`.xlsx`, `.xlsm`), CSV/TSV, Word (`.docx`), PDF, text/Markdown, or pasted text
- **Embeddings:** local multilingual ONNX models (FastEmbed), any OpenAI-compatible
  `/embeddings` endpoint (OpenAI, Ollama, TEI, vLLM…), or a dependency-free character
  n-gram hash
- **Optional second stage:** cross-encoder re-ranking (`bge-reranker-v2-m3`)
- **Storage:** [Qdrant](https://qdrant.tech) for both vectors and metadata
- **UI:** React + Vite, Persian and English, results export to CSV

## Quick start (Docker)

```bash
cp backend/.env.example .env      # optional: edit values
docker compose up -d --build
```

Open <http://localhost:8080>. By default the web port is bound to `127.0.0.1`
only. To reach it from other machines, **set an access token first** (see
[Security](#security)):

```bash
SIM_API_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))") \
WEB_BIND=0.0.0.0 docker compose up -d
```

## Local development

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 22+.

```bash
# API (embedded Qdrant on disk; add --extra local for FastEmbed models)
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000

# Web UI (proxies /api to localhost:8000)
cd frontend
npm ci
npm run dev
```

Checks:

```bash
cd backend && uv run pytest && uv run ruff check .
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

## Configuration

All API settings are environment variables prefixed with `SIM_` — see
[`backend/.env.example`](backend/.env.example). The Qdrant and LLM connections
can also be changed from the **Settings** page; those values are saved to
`<SIM_DATA_DIR>/settings.json` (mode `0600`) and override the environment.

| Variable | Purpose |
| --- | --- |
| `SIM_API_TOKEN` | Shared access token. When set, every `/api/` call needs `Authorization: Bearer <token>`; the UI asks for it once. |
| `SIM_DATA_DIR` | Where runtime settings, embedded Qdrant files and downloaded models live. |
| `SIM_QDRANT_URL` / `SIM_QDRANT_API_KEY` | Qdrant server. Empty URL = embedded on-disk Qdrant (single process, dev only). |
| `SIM_OPENAI_BASE_URL` / `SIM_OPENAI_API_KEY` | OpenAI-compatible embeddings endpoint. |
| `SIM_LLM_*` | Chat LLM connection (`openai`-compatible or `anthropic`). |
| `SIM_CORS_ORIGINS` | JSON list of allowed browser origins when the UI is served from another origin. |
| `SIM_MAX_UPLOAD_MB` | Upload size limit (keep in step with `client_max_body_size` in `frontend/nginx.conf`). |

## Security

Similarityly has **no user accounts**. Protect it with one of:

1. `SIM_API_TOKEN` — a shared bearer token checked on every API request
   (constant-time comparison). Strongly recommended for any non-local deployment.
2. Keep it local-only (the Docker default binds to `127.0.0.1`), or put it
   behind your own authenticating reverse proxy / VPN.

Without a token, anyone who can reach the API can read, change and delete all
data and change the connection settings. Always serve it over HTTPS when it
leaves your machine — the token and uploaded data travel in every request.

Other hardening in place: saved API keys are write-only (never returned by the
API) and are never sent to an endpoint other than the one they were saved for;
CSV exports neutralize spreadsheet formulas; uploads are size-capped while
streaming; the API container runs as a non-root user; nginx sends a strict
Content-Security-Policy and related headers.

> **Upgrading an existing Docker volume:** the API container now runs as UID
> 10001. If the `api_data` volume was created by an older (root) image, fix its
> ownership once: `docker compose run --rm -u root api chown -R 10001:10001 /data`.

Please report vulnerabilities privately — see [SECURITY.md](SECURITY.md).

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
