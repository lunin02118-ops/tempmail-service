# Free-Tier Implementation Backlog

## Current Execution Status

Status legend:

- `[x]` completed
- `[-]` in progress
- `[ ]` pending

### Tracked Build Plan

- `[x]` Finalize product shape: session-bound temp mailboxes, unified inbox, mailbox-specific history, AI side panel, popup notifications
- `[x]` Secure and store local infrastructure secrets outside the repository
- `[x]` Verify Cloudflare access and identify the working zone/account layout
- `[x]` Create Turnstile widget and keep its site/server keys only in local environment variables
- `[x]` Prepare Neon database and keep pooled/direct connection strings only in local environment variables
- `[x]` Audit the existing codebase and mark Gmail/Telegram pieces as legacy paths
- `[x]` Migrate configuration layer toward free-tier architecture with Neon, Cloudflare, Render, and Groq settings
- `[x]` Migrate database bootstrap from SQLite-only setup to SQLAlchemy with legacy plus new tempmail tables
- `[x]` Stabilize repository layer after SQLAlchemy migration and close compatibility regressions
- `[x]` Add repositories for mailboxes, unified inbox reads, messages, and AI extraction results
- `[x]` Implement domain services for mailbox creation, session-token hashing, TTL handling, and unified inbox aggregation
- `[x]` Implement Groq key rotation and persistence of AI extraction results
- `[x]` Add provider-agnostic inbound mail ingest flow so the product is not tied to Gmail APIs
- `[x]` Add new FastAPI endpoints for mailbox creation, mailbox listing, unified inbox, mailbox history, message detail, and AI analysis
- `[x]` Prepare notification-ready event payloads for browser popup and future desktop widget surfaces
- `[-]` Update environment examples and deployment docs for Render + Neon + Cloudflare
- `[x]` Add tests for config, DB bootstrap, mailbox lifecycle, unified inbox queries, and AI extraction flows
- `[-]` Run local validation and document deployment readiness for the next Render step

### Active Step Right Now

The current implementation focus is:

- getting the first deploy target ready so `APP_INGEST_URL` can be replaced with a real Render URL
- only after that, binding Cloudflare Email Routing catch-all to the new Email Worker

### Cloudflare Email Worker Status

- `[x]` Email Worker scaffold added at `workers/email-ingest`
- `[x]` TypeScript handler added for Cloudflare Email Routing events
- `[x]` Recipient domain validation added
- `[x]` Raw email size guard added before reading the stream
- `[x]` Best-effort `text/plain` and `text/html` MIME extraction added
- `[x]` Stable `provider_message_id` generation added
- `[x]` Signed JSON handoff to `POST /ingest/messages` added
- `[x]` Worker docs and `.dev.vars.example` added
- `[x]` `npm run typecheck` passes
- `[x]` `npx wrangler deploy --dry-run` passes
- `[ ]` Replace placeholder `APP_INGEST_URL` with the real Render URL
- `[ ]` Set Cloudflare Worker secret `INGEST_WEBHOOK_SECRET`
- `[ ]` Deploy Worker to Cloudflare
- `[ ]` Bind Email Routing catch-all to the Worker after confirming domain-mail impact

## Goal

Ship a real temporary email MVP on free plans with:

- inbound email receiving
- mailbox history per inbox
- one unified inbox window across all mailboxes in the current session
- browser inbox UI
- deterministic OTP extraction
- on-demand AI analysis for each email
- Groq key rotation
- popup notification with code or short AI summary

## Required Services

### 1. Cloudflare

Purpose:

- DNS
- Email Routing catch-all
- Email Worker
- Turnstile
- optional R2 storage

What we need from you:

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_ZONE_ID`
- domain that will receive temp mail, for example `mail.example.com`

Recommended token permissions:

- Zone: Read
- DNS: Edit
- Email Routing: Edit
- Workers Scripts: Edit
- Workers Routes: Edit
- Account Settings: Read
- Turnstile: Edit
- R2: Edit, only if we use direct R2 API setup

### 2. Neon

Purpose:

- relational storage for mailboxes, messages, history, AI analysis, sessions

What we need from you:

- `DATABASE_URL`
- `DATABASE_URL_DIRECT`

Optional for automation:

- `NEON_API_KEY`

### 3. Groq

Purpose:

- AI analysis of each email
- summary
- category
- OTP confidence scoring
- action extraction
- optional draft replies later

What we need from you:

- at least 2 API keys for rotation

Recommended env format:

- `GROQ_API_KEYS=key1,key2,key3`

Alternative format:

- `GROQ_API_KEY_1=...`
- `GROQ_API_KEY_2=...`
- `GROQ_API_KEY_3=...`

### 4. Render

Purpose:

- one free web service for API and inbox reads

What we need from you:

- no API key is required for manual dashboard deploy

Optional if we automate later:

- `RENDER_API_KEY`

## Required Secrets That Are Not API Keys

These are also mandatory:

- `SESSION_SECRET`
- `INGEST_WEBHOOK_SECRET`
- `TURNSTILE_SITE_KEY`
- `TURNSTILE_SECRET_KEY`

Optional:

- `APP_BASE_URL`
- `PUBLIC_MAIL_DOMAIN`

## Exact MVP Secret Set

Minimum practical set:

- `APP_ENV`
- `APP_BASE_URL`
- `PUBLIC_MAIL_DOMAIN`
- `DATABASE_URL`
- `DATABASE_URL_DIRECT`
- `SESSION_SECRET`
- `INGEST_WEBHOOK_SECRET`
- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_ZONE_ID`
- `TURNSTILE_SITE_KEY`
- `TURNSTILE_SECRET_KEY`
- `GROQ_API_KEYS`

Optional for the first iteration:

- `NEON_API_KEY`
- `RENDER_API_KEY`
- `R2_BUCKET_NAME`
- `R2_PUBLIC_BASE_URL`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`

## Storage Strategy

### Mailbox history

Persist in Neon:

- mailbox
- sender
- subject
- received time
- parsed text
- html preview or sanitized html
- AI summary
- extracted code
- action links
- status

### Raw MIME

Two launch options:

#### Option A: no raw MIME in MVP

- simplest
- cheapest
- store parsed message content only
- best for fast launch

#### Option B: raw MIME in R2

- better auditability
- better parser debugging
- better future attachment support

Recommendation:

Start with Option A if we want the fastest path.

Add R2 in phase 2.

## Groq Rotation Strategy

### Required behavior

- round-robin between available keys
- on `429`, move to the next key
- on `401`, disable the failing key from the active pool
- on `5xx`, retry once with the next key
- never log raw keys

### Safe strategy

Store active keys in memory at app startup and expose only:

- key index
- request counts
- rate-limit events

Do not expose:

- full key
- partial key in logs

### Usage policy

Run Groq only:

- on mailbox open
- on button click
- on-demand per message

Do not run it automatically for every inbound email in the free-tier MVP.

## MVP Architecture

### Recommended version

- Cloudflare Email Routing catch-all
- Cloudflare Email Worker
- Render free web service
- Neon free database
- Turnstile free
- Groq free with rotation
- browser notification surface for urgent results

### Flow

1. User creates a temp mailbox in the browser.
2. App stores mailbox in Neon with session binding.
3. Incoming email hits Cloudflare catch-all.
4. Email Worker resolves mailbox by local-part.
5. Worker sends normalized payload to the app ingest endpoint.
6. Render app stores the message in Neon.
7. Unified inbox UI shows all messages from all mailboxes in the current session.
8. User can filter the same list by mailbox to see mailbox-specific history.
9. User opens one message.
10. User clicks analyze.
11. App calls Groq using the next available key.
12. Result is stored in Neon and shown in the AI side panel.
13. Important results also appear as a compact popup so the user does not need to search manually.

## Phase Plan

### Phase 1

- Neon schema
- mailbox model
- message history model
- session model
- base FastAPI endpoints

### Phase 2

- browser inbox UI
- create mailbox flow
- message list
- message detail

### Phase 3

- Cloudflare Email Worker
- signed ingest endpoint
- deterministic OTP extraction

### Phase 4

- Turnstile
- rate limits
- mailbox TTL cleanup

### Phase 5

- Groq integration
- key rotation
- summary panel
- per-email analysis action
- popup notification for important result

## First Deliverables

The first concrete implementation batch should produce:

- one inbox per session
- full history for that inbox
- one combined inbox window for the whole session
- inbound email persistence
- OTP extraction
- one-click AI analysis on each message
- popup notification for code or important summary

## What I Need From You Next

### Mandatory now

- final mail domain or subdomain for temp mail
- `CLOUDFLARE_ZONE_ID`
- `DATABASE_URL`
- `DATABASE_URL_DIRECT`
- `TURNSTILE_SITE_KEY`
- `TURNSTILE_SECRET_KEY`
- 2 or more Groq keys

### Nice to have

- `NEON_API_KEY`
- `RENDER_API_KEY`

## Recommendation

If the goal is free-tier only, the cleanest MVP is:

- no public inboxes
- no outbound sending
- no attachment-heavy workflow
- no auto-analysis for every message

Just:

- receive
- persist history
- aggregate all mailboxes into one working window
- inspect
- extract OTP
- analyze on demand
