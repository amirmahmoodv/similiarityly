# Similarityly
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
- **UI:** React + Vite, Persian and English, results export to CSV or Excel (top match candidates with their labels, pivoted into columns or one row per candidate)

## Quick start (Docker)

```bash
cp .env.example .env              # optional: access token, ports
docker compose up -d --build
```

Open <http://localhost:8080>. By default the web port is bound to `127.0.0.1`
only. To reach it from other machines, **set an access token first** (see
[Security](#security)):

```bash
SIM_API_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))") \
WEB_BIND=0.0.0.0 docker compose up -d
```

### UI and API on separate domains

By default the browser calls the API under `/api` on the UI's own origin and the
`web` container proxies it. To serve the API from its own domain instead, e.g.
UI at `https://sim.example.com` and API at `https://api.sim.example.com`, set in
`.env`:

```bash
API_URL=https://api.sim.example.com      # what the browser calls
SIM_CORS_ORIGINS=https://sim.example.com # the UI's origin, allowed by the API
SIM_API_TOKEN=...                         # required: the API is now public
```

Then point the UI domain at the `web` port (8080) and the API domain at the `api`
port (8000), each behind your TLS reverse proxy. `API_URL` is applied when the
`web` container starts (it writes `/config.js` and the CSP `connect-src`), so
changing it needs only `docker compose up -d`, not a rebuild. Give the API
proxy an upload limit and timeouts (e.g. `client_max_body_size 60m`,
`proxy_read_timeout 300s` in nginx): uvicorn itself has no body-size limit.

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

Connections are set on the **Settings** page: the Qdrant server, the
OpenAI-compatible embedding service and the language model. They are saved to
`<SIM_DATA_DIR>/settings.json` (mode `0600`). With nothing saved, the API uses
`SIM_DEFAULT_QDRANT_URL` (embedded on-disk Qdrant if unset; Docker: the bundled
`qdrant` service) and OpenAI's default endpoint.

Only process-level settings stay in the environment — see
[`.env.example`](.env.example) for Docker and
[`backend/.env.example`](backend/.env.example) for running the API directly:

| Variable | Purpose |
| --- | --- |
| `SIM_API_TOKEN` | Shared access token. When set, every `/api/` call needs `Authorization: Bearer <token>`; the UI asks for it once. |
| `SIM_DEFAULT_QDRANT_URL` | Qdrant server used until one is saved in Settings (compose sets it to the bundled service). Empty = embedded. |
| `SIM_QDRANT_TIMEOUT` | Seconds per request to a Qdrant server (default 60). Raise it for a slow or distant Qdrant. |
| `SIM_DATA_DIR` | Where runtime settings, embedded Qdrant files and downloaded models live. |
| `SIM_CORS_ORIGINS` | Browser origins allowed to call the API from another origin (comma-separated or JSON list). Only for a separate API domain. |
| `SIM_ENABLE_DOCS` | Serve `/docs` and `/openapi.json` (off by default). |
| `SIM_ALLOW_PUBLIC_WITHOUT_TOKEN` | Let the API start with a public `SIM_CORS_ORIGINS` and no token — only behind an authenticating proxy. |
| `SIM_MAX_UPLOAD_MB` | Upload size limit (keep in step with `client_max_body_size` in `frontend/nginx.conf`). |
| `API_URL` | Docker `web` service: public URL of the API when it has its own domain. Empty = `/api` on the UI's origin. |
| `API_UPSTREAM` | Docker `web` service, same-origin mode only: where nginx proxies `/api/` (default `http://api:8000`). |
| `WEB_BIND` / `WEB_PORT` / `API_BIND` / `API_PORT` / `QDRANT_PORT` | Docker host interfaces and ports. |

The old connection variables (`SIM_QDRANT_URL`, `SIM_QDRANT_API_KEY`,
`SIM_OPENAI_*`, `SIM_LLM_*`) are **ignored**; set those values in Settings.

## Protecting stored data

Everything lives in Qdrant, including the full text of every loaded record.
If Qdrant is killed in the middle of a write, or its disk fills up, stored
payloads can be left damaged: reads then fail with
`Failed to decode value: Failed to decompress LZ4 value`. The app cannot
prevent that from the outside; the Qdrant deployment has to:

- **Let Qdrant shut down cleanly.** Compose gives it two minutes
  (`stop_grace_period`). On Kubernetes set `terminationGracePeriodSeconds`
  to 60 or more and never force-delete the pod.
- **Give it enough memory and disk.** An out-of-memory kill during a large
  load is the usual cause. Set a memory limit with headroom and alert on the
  volume filling up.
- **Use block storage** (a local disk or a cloud block volume), not NFS or
  another network file system. Qdrant requires a POSIX file system.
- **Take snapshots** (`POST /collections/{name}/snapshots` on Qdrant) of at
  least `sim_meta_records` on a schedule. A snapshot is the only way to get
  damaged text back.

What the app does when it happens anyway:

- Each batch written to a Qdrant server is read back at once, so a write that
  cannot be decoded fails the load instead of surfacing days later.
- The API answers `503` with the code `storage_corrupt` (other Qdrant 5xx
  answers: `storage_error`) instead of an unexplained `500`.
- The **Chunks** tab leaves damaged records out, says how many, and offers
  **Remove damaged records** (`POST /api/v1/repos/{id}/repair`). Qdrant
  cannot delete a point it cannot decode: the delete fails and the collection
  then refuses every write (`Not recovered from previous error`). So the
  repair copies every record that still decodes to a side collection
  (`sim_meta_records_rebuild`), drops and recreates the damaged collection,
  and moves the copy back, for all repositories at once. The lost records'
  chunks and matches are removed too. An interrupted repair is finished at
  the next API start. Load the affected files again afterwards.
- Deleting a source or repository that holds damaged records is refused with
  `storage_corrupt` until it has been repaired, for the same reason.

## Security

Similarityly has **no user accounts**. Protect it with one of:

1. `SIM_API_TOKEN` — a shared bearer token checked on every API request
   (constant-time comparison). Strongly recommended for any non-local deployment.
2. Keep it local-only (the Docker default binds to `127.0.0.1`), or put it
   behind your own authenticating reverse proxy / VPN.

Without a token, anyone who can reach the API can read, change and delete all
data and change the connection settings. Always serve it over HTTPS when it
leaves your machine — the token and uploaded data travel in every request.

The API **refuses to start** when `SIM_CORS_ORIGINS` names a public origin
(anything but `localhost`/`127.0.0.1`) and no token is set, and it rejects `*`
as an origin. A token shorter than 16 characters is logged as a warning.

Other hardening in place:

- Saved API keys are write-only (never returned by the API) and are never sent
  to an endpoint other than the one they were saved for.
- Request bodies are capped by the API itself (`SIM_MAX_UPLOAD_MB` + 1 MB),
  before parsing, so it is safe without a proxy limit in front.
- API responses carry `Cache-Control: no-store`, a deny-all CSP, `nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and HSTS; `/docs` and
  `/openapi.json` are off unless `SIM_ENABLE_DOCS=true`; no `Server` header.
- The web container sends a strict Content-Security-Policy (scripts from its
  own origin only; `connect-src` limited to the API), `frame-ancestors 'none'`,
  `Cross-Origin-Opener-Policy`, HSTS and related headers.
- Containers run with `no-new-privileges`; the API runs as a non-root user with
  no Linux capabilities and a read-only root filesystem (only `/data` and
  `/tmp` are writable). CSV exports neutralize spreadsheet formulas.

HSTS only takes effect over HTTPS; terminate TLS in your reverse proxy and
redirect plain HTTP to HTTPS there.

> **Data volume ownership:** the API always runs as UID 10001. Started with the
> image's default user (as most platforms do), the entrypoint first gives
> `SIM_DATA_DIR` (`/data`) to UID 10001 if a mounted volume belongs to someone
> else, e.g. a root-owned platform volume, then drops root before the app starts.
> This needs the `CHOWN`, `SETUID` and `SETGID` capabilities, which containers
> have by default. `docker-compose.yml` instead starts it as `10001:10001` with no
> capabilities; if its `api_data` volume was created by an older root image, fix
> it once: `docker compose run --rm -u root api chown -R 10001:10001 /data`. If
> `/data` is not writable, the container exits with a message saying how to fix it.

Please report vulnerabilities privately — see [SECURITY.md](SECURITY.md).

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
