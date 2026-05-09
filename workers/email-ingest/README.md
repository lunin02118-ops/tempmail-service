# Temp Mail Email Ingest Worker

This Cloudflare Email Worker receives catch-all routed email and forwards a normalized JSON payload to the FastAPI backend endpoint:

```text
POST /ingest/messages
```

## What It Does

- validates the recipient domain
- rejects oversized emails before reading the raw stream
- extracts a best-effort `text/plain` and `text/html` body
- builds a stable `provider_message_id`
- sends normalized metadata, body text, headers, raw size, and a small raw excerpt to the backend
- never stores or prints secrets

## Required Variables

Non-secret variables live in `wrangler.jsonc`:

```jsonc
{
  "vars": {
    "APP_INGEST_URL": "https://your-render-app.onrender.com/ingest/messages",
    "PUBLIC_MAIL_DOMAINS": "samgpt.me,sawdd34.tech",
    "MAX_RAW_BYTES": "1048576"
  }
}
```

Secret variable:

```bash
npx wrangler secret put INGEST_WEBHOOK_SECRET
```

Use the same value as the backend `INGEST_WEBHOOK_SECRET`.

## Local Checks

```bash
npm install
npm run typecheck
npx wrangler deploy --dry-run
```

## Deploy

Update `APP_INGEST_URL` in `wrangler.jsonc`, then run:

```bash
npx wrangler deploy
```

## Bind to Email Routing

After the Worker is deployed:

1. Open Cloudflare dashboard.
2. Go to the target zone.
3. Open Email Routing.
4. Enable Email Routing if it is not already enabled.
5. Add a catch-all route or custom address route.
6. Set the destination to the `tempmail-email-ingest` Email Worker.

Changing MX/catch-all routing affects real domain email delivery. Do this only after the Render backend URL and `INGEST_WEBHOOK_SECRET` are correct.
