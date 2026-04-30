# Deploy Guide

## Primary Deploy Path

Use the current production stack:

- Render for the FastAPI app
- Neon Postgres for persistence
- Cloudflare for DNS, Email Routing, Worker, and Turnstile

The Render blueprint is stored in [`render.yaml`](../render.yaml).

## Render Web Service

Start command:

```bash
uvicorn app.main:create_app --factory --host 0.0.0.0 --port $PORT
```

Install command:

```bash
pip install -r requirements.txt
```

## Required Environment Variables

```env
APP_ENV=prod
LOG_LEVEL=INFO
DATABASE_URL=postgresql+psycopg://...
DATABASE_URL_DIRECT=postgresql+psycopg://...
PUBLIC_MAIL_DOMAIN=mail.example.com
PUBLIC_MAIL_DOMAINS=mail.example.com,alt.example.com
SESSION_SECRET=change-me
INGEST_WEBHOOK_SECRET=change-me
GROQ_API_KEYS=key1,key2
ARCHIVE_ADMIN_TOKEN=change-me
```

Turnstile is disabled by default. Set `TURNSTILE_ENABLED=true` together with `TURNSTILE_SITE_KEY` and
`TURNSTILE_SECRET_KEY` only when the human check should be active.

## Cloudflare Worker

Worker files:

- [`workers/email-ingest/src/index.ts`](../workers/email-ingest/src/index.ts)
- [`workers/email-ingest/wrangler.jsonc`](../workers/email-ingest/wrangler.jsonc)

Typical flow:

```bash
cd workers/email-ingest
npm install
npm run typecheck
npx wrangler deploy --dry-run
npx wrangler secret put INGEST_WEBHOOK_SECRET
npx wrangler deploy --keep-vars
```

Bind Email Routing only after:

1. `APP_INGEST_URL` points at the real Render service
2. `INGEST_WEBHOOK_SECRET` matches Render
3. allowed mail domains are configured consistently

## Notes

- local build artifacts like `build/`, `output/`, and `.pytest_cache/` are not part of deployment
- archived VPS/systemd deploy assets live under [`legacy/standalone/`](../legacy/standalone/)
