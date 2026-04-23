# SamGPT Temp Mail

Disposable mailboxes with a web inbox, admin archive, OTP extraction, and a desktop widget.

## Current Stack

- FastAPI app served on Render
- Neon Postgres for mailbox and message storage
- Cloudflare Email Routing + Email Worker for inbound email
- Groq for optional message analysis
- Windows desktop widget in `windows_widget/`

## Repository Layout

- `app/` application code, APIs, repositories, services, static UI
- `workers/email-ingest/` Cloudflare Email Worker
- `windows_widget/` desktop widget host and build scripts
- `docs/` current docs, plans, and archived notes
- `legacy/standalone/` old VPS/systemd assets kept only for reference
- `tests/` Python test suite

## Local Run

```bash
pip install -r requirements.txt
uvicorn app.main:create_app --factory --reload
```

Create local secrets in `.env.local` based on `.env.example`.

## Main Entry Points

- [`app/main.py`](app/main.py)
- [`app/api/tempmail.py`](app/api/tempmail.py)
- [`app/api/admin_archive.py`](app/api/admin_archive.py)
- [`workers/email-ingest/src/index.ts`](workers/email-ingest/src/index.ts)
- [`windows_widget/widget_host.py`](windows_widget/widget_host.py)

## Documentation

- [`docs/README.md`](docs/README.md) documentation index
- [`docs/architecture.md`](docs/architecture.md) current architecture
- [`docs/deploy.md`](docs/deploy.md) current deploy flow
- [`docs/implementation.md`](docs/implementation.md) implementation notes
- [`docs/plans/`](docs/plans/) product and rollout plans
- [`docs/legacy/README.md`](docs/legacy/README.md) archived standalone notes
