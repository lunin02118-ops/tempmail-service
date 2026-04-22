# Temp Mail Service Plan

## Product Direction

Turn the current mail-to-Telegram integration into a real temporary email product with a browser inbox, instant mailbox creation, live message delivery, code extraction, and AI-assisted summaries.

Launch target:

- database: Neon Postgres
- backend and worker runtime: Render
- email edge, DNS, anti-abuse, and optional object storage: Cloudflare
- AI extraction layer: Groq

## Free-Tier First Constraint

The first release should fit inside free plans and free monthly limits.

That changes the system shape:

- no paid Render worker
- no paid Render cron jobs
- no paid Cloudflare Workers plan
- no paid Neon plan
- no paid Groq plan

So the MVP must favor:

- one primary web backend
- lightweight edge ingestion
- lazy AI calls
- aggressive TTL cleanup
- graceful cold-start behavior

## Executive Decision

Do not build the next version on top of Gmail API.

The current Gmail-based design is useful as a bridge and for validating parsing logic, but it is the wrong foundation for a Yopmail-like product because:

- mailbox creation is not native to Gmail
- catch-all and arbitrary inbox creation are unnatural in the Gmail model
- operational control is weak compared to true inbound email providers
- delivery behavior and polling create avoidable latency and reliability risks
- scaling public disposable inboxes through one mailbox is the wrong abstraction

## Recommended Launch Mode

### Mode A: public inboxes

- URL pattern: `/inbox/<name>`
- closest to Yopmail
- highest abuse, scraping, and privacy risk

### Mode B: session-locked generated inboxes

- system creates a random local part
- inbox is bound to a browser session token
- safer anti-abuse posture
- better first launch path

### Recommended launch

Ship Mode B first.

Add public inboxes later only after:

- abuse controls are proven
- indexing and cleanup are stable
- sender and attachment restrictions are in place

For a free-tier launch, public inboxes should stay out of scope.

## Required User Experience

The product should support both:

- history per individual mailbox
- one unified operator window with all incoming emails in one place

This means the UI should not force the user to jump between isolated inbox pages just to find the latest code.

### Recommended UX model

#### View 1: unified inbox

- one screen shows all emails from all mailboxes visible to the current session
- default sorting by newest first
- quick filters by mailbox, sender, subject, has-code, unread, analyzed
- this is the main working screen

#### View 2: mailbox history

- click on a mailbox badge to filter the unified inbox
- same message list, but scoped to one mailbox
- preserves full history for that mailbox

#### View 3: message detail

- open one message in the center panel
- show sender, subject, received time, body preview, mailbox name

#### View 4: AI side panel

- separate panel on the right
- shows extracted OTP code first
- then short summary
- then action links
- then optional suggested reply draft later

#### View 5: desktop-style notification surface

- a tiny popup or widget-like surface for the active session
- shows the most important new result immediately
- designed for "do not make me search for the code"
- clicking it opens the full message in the main app

### Important implementation note

Do not duplicate message storage.

Store each message once in the database and expose:

- aggregated read model for the unified inbox
- filtered read model for mailbox-specific history

The "one window" requirement is a UI and query-layer feature, not a data duplication requirement.

### Recommended rollout for desktop notifications

#### Stage 1: browser notifications

- fastest and cheapest path
- works with an installable PWA
- no extra infrastructure beyond the web app
- best free-tier starting point

#### Stage 2: lightweight desktop widget

- small always-on-top mini window
- consumes the same session feed as the web app
- better if you want a true desktop widget feeling on Windows

Recommendation:

Ship Stage 1 first, then build Stage 2 if the notification workflow proves valuable.

## Target Architecture

### Recommended reference architecture

1. Cloudflare DNS hosts the domain.
2. Cloudflare Email Routing catch-all sends inbound mail to an Email Worker.
3. Email Worker performs first-pass validation and normalization.
4. Raw MIME and attachments are stored in object storage.
5. Metadata is placed on an async queue.
6. Render ingestion API and worker persist structured data into Neon.
7. Browser clients receive updates through SSE or WebSocket.
8. Groq runs async extraction jobs for summaries, OTP codes, links, and reply drafts.

### Best practical split

Use Cloudflare for edge mail ingress and abuse control.

Use Render for application logic, APIs, background jobs, and business rules.

Use Neon as the system-of-record database.

Use object storage for raw MIME and attachments. If Cloudflare is already the ingress layer, R2 is the most natural fit.

### Free-tier adjustment

On free plans, do not assume separate always-on backend processes.

Practical free-tier split:

- one free Render web service for API and inbox reads
- Cloudflare Worker for inbound mail ingress
- optional Cloudflare Queue for buffering
- no dedicated Render worker in MVP
- no Render cron in MVP

## Preferred Stack by Layer

### Frontend

- React or Next.js inbox UI
- initial deploy can live on the same Render web service
- later split to Cloudflare Pages if we want lower-cost static delivery

### Backend

- FastAPI is still a good fit
- keep API and background processing as separate services
- do not keep state on local disk

Free-tier note:

- keep FastAPI on a single Render free web service
- move background-heavy pieces to Cloudflare where possible

### Realtime

- SSE first, simpler than WebSocket for inbox updates
- WebSocket only if we later need multi-pane collaboration or richer live presence

### Database

- Neon Postgres for mailboxes, messages, AI results, abuse scoring, and sessions
- use pooled connections in production
- use direct connections only for migrations and admin jobs

### Object Storage

- Cloudflare R2 for raw MIME, attachments, and optional HTML snapshots
- store only metadata in Neon, not large bodies as the primary source of truth

## Detailed Inbound Flow

### Step 1: receive mail

- email arrives at `anything@yourdomain.tld`
- Cloudflare catch-all route sends it to an Email Worker

### Step 2: edge validation

Worker checks:

- recipient format
- sender metadata
- message size
- simple deny rules
- abuse heuristics

### Step 3: persist raw payload

Worker stores:

- raw MIME
- attachment metadata
- envelope metadata

Recommended key pattern:

- `raw/<yyyy>/<mm>/<dd>/<message-id>.eml`
- `attachments/<message-id>/<filename>`

### Step 4: async handoff

Worker sends a normalized event to a queue with:

- message identifier
- mailbox local-part
- R2 object keys
- sender
- subject
- received timestamp
- raw size

### Step 5: application ingestion

Render ingestion service:

- validates the event signature
- upserts the mailbox
- creates message records
- schedules parsing and AI jobs

### Step 6: parse and enrich

Render worker:

- extracts text and HTML
- normalizes sender and subject
- computes hash for idempotency
- runs deterministic OTP and link extraction
- triggers Groq enrichment only when useful

### Step 7: fan-out to clients

- browser inbox updates through SSE
- optional Telegram notification can remain as a secondary channel, not the primary UX

## Why Cloudflare Is the Best Default Edge

### What Cloudflare does well for this product

- DNS and mail routing in one place
- catch-all routing support
- Worker-based programmable inbound handling
- built-in anti-bot tools such as Turnstile
- WAF and rate limiting for public endpoints
- Queues for retries and DLQ patterns
- optional AI Gateway layer in front of Groq

### Important Cloudflare caveats

- Email Service is currently beta
- Email Service is available on Workers Paid plan
- Email Routing message size limit is 25 MiB
- classic per-address rules are capped, so the product should use catch-all routing instead of creating one rule per mailbox
- forwarding-only architectures still inherit email-forwarding caveats like restrictive DMARC behavior

### Free-tier notes

- Email Routing is available on Workers Free and Workers Paid plans
- inbound email routing itself is unlimited
- Email Routing Workers consume Workers quota
- Workers Free currently includes 100,000 requests per day and 10 ms CPU time per invocation by default
- Turnstile free plan is enough for MVP anti-bot protection
- Queues are available on Workers Free with 10,000 operations per day and 24-hour retention
- R2 has a monthly free tier, but retention must stay tight

### Recommended Cloudflare pattern

Use catch-all routing plus a Worker action, not one route per temporary inbox.

That keeps mailbox creation virtual and lets the app treat the local-part as application data instead of infrastructure state.

## Better Alternatives Than Gmail

### Option 1: Cloudflare Email Routing + Email Worker

Best when:

- we want Cloudflare to be the edge and abuse control layer
- we want catch-all routing
- we want full programmable logic at receive time

Pros:

- tight Cloudflare integration
- edge filtering before the backend
- good fit for disposable inboxes
- can keep raw MIME available in Worker

Cons:

- Email Service is beta
- inbound size limit is 25 MiB
- should be tested carefully before committing to very large-scale public inbox traffic

### Option 2: Resend Inbound

Best managed webhook-first alternative.

Pros:

- inbound via webhooks
- full content retrieval API
- attachments metadata and download URLs
- dashboard visibility and retry behavior
- built-in redundancy language in product docs

Cons:

- less edge programmability than Cloudflare-first ingress
- more vendor dependence for inbound mail handling

Recommended use:

- strongest fallback choice if we decide Cloudflare Email Service beta risk is too high for launch

### Option 3: Mailgun Routes

Best mature routing option for regex-based inbound handling.

Pros:

- route expressions support recipient regex captures
- can forward parsed payloads to HTTP endpoints
- can store incoming messages temporarily
- raw MIME delivery option exists

Cons:

- more classic ESP workflow
- less elegant if we want Cloudflare-native edge controls

### Option 4: Postmark Inbound

Best clean inbound JSON pipeline for transactional-style applications.

Pros:

- clean inbound JSON webhook
- reply parsing helpers
- spam headers included
- plus-address workflows are well supported

Cons:

- less natural for fully arbitrary public temp inboxes than a catch-all Worker model

### Option 5: AWS SES Receiving

Best industrial-strength control plane.

Pros:

- raw MIME to S3
- Lambda and SNS hooks
- high control and durability

Cons:

- highest operational complexity
- overkill for MVP unless we already want an AWS-heavy stack

### Recommendation

Use this provider order:

1. Cloudflare Email Routing + Worker for MVP exploration
2. Resend Inbound as the managed fallback if Cloudflare beta behavior is not production-comfortable
3. AWS SES if we later need maximum control and are willing to absorb more ops complexity

## Outbound Strategy

For MVP, do not auto-send replies.

For a strict free-tier MVP, do not ship outbound mail at all.

Phase the outbound side like this:

1. no outbound, only AI drafts in UI
2. operator-approved sends
3. limited user-approved replies

If real outbound delivery is added early, use a dedicated sending provider first. Cloudflare Email Service outbound is promising, but it is still beta. Resend or Postmark may be a better first outbound provider for production reliability.

## AI Strategy with Groq

### Principle

Use deterministic extraction first, AI second.

OTP and action-link extraction should not depend purely on an LLM.

### Stage 1: deterministic extraction

- OTP regexes
- sender-brand heuristics
- login / verify / reset URL extraction
- expiry phrase detection
- unsubscribe and security-notice detection

### Stage 2: Groq structured extraction

Run Groq asynchronously for:

- short summary
- message type
- sender brand
- action required
- urgency
- OTP candidate confidence
- suggested next step

Recommended contract:

- strict JSON schema output where possible
- retry only on best-effort models
- never block inbox rendering on AI completion

### Current Groq constraint to plan around

Groq Structured Outputs currently has strict mode only on select models, and structured outputs do not currently support streaming or tool use.

That means the AI panel should be an async enrichment panel, not part of the critical path for inbox open.

### Stage 3: reply drafts

Show draft suggestions in a separate assistant pane:

- concise reply
- formal reply
- support reply
- security / verification reply

No auto-send in launch version.

### Stage 4: user actions

Later:

- one-click copy code
- one-click open action link
- one-click paste reply draft into outbound composer

## Suggested Core Data Model

### mailboxes

- id
- local_part
- domain
- address
- visibility
- session_token_hash
- status
- expires_at
- created_at
- last_seen_at

### messages

- id
- mailbox_id
- provider
- provider_message_id
- from_address
- reply_to
- subject
- received_at
- raw_mime_key
- text_body
- html_body
- size_bytes
- has_attachments
- spam_score
- delivery_status
- ai_status
- is_unread
- session_scope

### attachments

- id
- message_id
- storage_key
- filename
- mime_type
- size_bytes
- sha256

### message_events

- id
- message_id
- event_type
- payload_json
- created_at

### ai_extractions

- id
- message_id
- provider
- model
- summary
- message_type
- otp_code
- action_link
- sender_brand
- urgency
- confidence
- created_at

### reply_drafts

- id
- message_id
- tone
- language
- draft_text
- created_at

### abuse_events

- id
- mailbox_id
- ip_hash
- ua_hash
- event_type
- score
- details_json
- created_at

## Abuse and Privacy Controls

### Must-have controls

- Turnstile on mailbox creation and suspicious refreshes
- server-side Siteverify validation
- per-IP and per-session rate limits
- mailbox TTL
- attachment size caps
- blocked sender domains and MIME types
- noindex on inbox pages
- no public directory or search in MVP

### Recommended launch TTLs

- default inbox lifetime: 1 hour
- inactive mailbox cleanup: 24 hours
- raw MIME retention: 7 to 30 days depending on legal and support needs

### Public inbox warning

If public inbox mode is introduced, assume:

- scraping bots will index it
- users will paste sensitive content there
- attackers will test brute-force mailbox names

Plan public inbox mode as a separate security milestone, not just a UI toggle.

## Unified Inbox Read Model

### Main idea

Each mailbox keeps its own history, but the session also gets a unified inbox feed.

That lets the user:

- see every new email in one place
- switch quickly to a mailbox-specific history when needed
- open AI results without hunting through multiple inbox pages

### Required queries

- `list_session_messages(session_id)`
- `list_mailbox_messages(mailbox_id)`
- `get_message(message_id)`
- `list_recent_codes(session_id)`

### Recommended UI blocks

- left rail: mailbox list
- center: unified message list
- main viewer: selected email
- right rail: AI extraction panel
- optional floating popup for latest urgent result

### AI panel priority

Show AI output in this order:

1. OTP or verification code
2. important action, for example verify, reset, login, confirm
3. one-line summary
4. sender brand
5. relevant links
6. optional reply suggestion

### Popup priority

The popup or widget surface should stay intentionally tiny.

Show only:

1. mailbox name
2. sender brand
3. OTP code if present
4. one-line summary
5. open action

## Neon Usage Plan

### Production recommendations

- use pooled connection strings in runtime services
- use direct connection strings for migrations
- keep one production branch, one staging branch
- use preview branches for risky schema or parser changes

### Scale-to-zero guidance

Neon scales inactive computes to zero after 5 minutes and reactivates within a few hundred milliseconds.

For a temp-mail inbox where open latency matters, keep production compute always warm if observed cold-start latency becomes noticeable.

### Why Neon is a strong fit here

- branch-based testing for parser changes
- safe preview environments
- easy isolation for experiments
- Postgres ecosystem compatibility

### Free-tier guidance

- Neon free is a better fit than Render free Postgres
- do not use Render free Postgres because it expires after 30 days and has no backups
- keep one Neon project for the MVP
- prune expired inboxes and old messages aggressively to stay within free storage

## Render Usage Plan

### Services

- `tempmail-web`: public API and inbox UI
- `tempmail-worker`: parsing, AI jobs, cleanup, provider sync
- `tempmail-cron`: optional scheduled cleanup and retention tasks

### Free-tier adjustment

On free Render, simplify this to:

- `tempmail-web`: the only Render service in MVP

Reason:

- free Render is suitable for a web service
- free web services spin down after 15 minutes of inactivity
- each workspace gets 750 free instance hours per month
- cron jobs have a minimum monthly charge
- dedicated workers are not part of the free-instance path we should rely on

### Deployment pattern

- use `render.yaml`
- deploy web and worker as separate services
- keep health endpoint simple
- never rely on local filesystem state

Free-tier deployment pattern:

- use `render.yaml`
- deploy one web service only
- treat Render as the UI and read API layer, not the ingestion queue

### What belongs on Render

- mailbox API
- inbox rendering
- SSE stream
- parsing jobs
- AI orchestration
- admin moderation endpoints

### What should move off Render on the free plan

- inbound email receipt
- retry buffering
- scheduled cleanup triggers
- any always-on background processing

These should live on Cloudflare where possible.

## Migration Strategy from the Current Codebase

### Reuse

- FastAPI application shape
- service / repository layering
- parsing tests and delivery tests
- worker patterns

### Replace

- Gmail client and polling logic
- SQLite persistence
- Telegram-first delivery assumptions
- file-path assumptions around local runtime data

### New modules required

- mailbox service
- inbound ingest service
- object storage service
- abuse scoring service
- realtime notification service
- AI extraction service
- draft generation service
- admin moderation service

## Implementation Phases

### Phase 0: architecture lock

- pick launch mode: session-locked only
- confirm inbound provider: Cloudflare-first
- confirm object storage: R2
- confirm frontend approach: same Render web service for MVP
- confirm free-tier mode: single Render web service only

### Phase 1: platform foundation

- Neon schema
- SQLAlchemy / Alembic migration setup
- Render `render.yaml`
- secrets and environment model
- R2 integration

### Phase 2: core mailbox UX

- create mailbox API
- session token issuance
- inbox page
- message list
- message detail
- SSE live updates

### Phase 3: inbound mail pipeline

- Cloudflare Email Worker
- catch-all routing
- raw MIME storage
- async queue handoff
- Render ingestion endpoint
- idempotent message persistence

Free-tier note:

- if Render wake-up latency is a problem, Cloudflare should write directly to Neon and let Render stay read-focused

### Phase 4: parsing and extraction

- MIME parsing
- text and HTML normalization
- deterministic OTP and link extraction
- attachment metadata

### Phase 5: AI assistant pane

- Groq structured extraction jobs
- summary cards
- code / link / CTA extraction
- suggested reply drafts

Free-tier note:

- Groq features should be user-triggered or sender-filtered, not automatic for every message

### Phase 5.5: notification surface

- browser notification for new important messages
- browser notification for extracted OTP codes
- compact desktop widget later if needed

### Phase 6: hardening

- Turnstile
- rate limiting
- abuse scoring
- admin review tools
- retention cleanup
- observability and alerting

### Phase 7: public inbox experiment

- optional named inboxes
- stronger abuse protections
- mailbox namespace reservation
- access friction for suspicious traffic

## MVP Scope

### Ship in MVP

- session-locked inboxes
- Cloudflare catch-all ingress
- Render web service only
- Neon Postgres
- R2 raw email storage
- unified inbox view
- mailbox-specific history view
- live inbox updates
- deterministic OTP extraction
- Groq summaries in async panel on demand
- popup notification for new code or important AI summary

### Do not ship in MVP

- arbitrary public inbox names
- full outbound replies
- auto-send AI replies
- large attachment handling beyond platform limits
- semantic search
- multi-user shared inboxes
- always-on worker infrastructure
- scheduled jobs that require paid runtimes
- native desktop widget app as the very first release

## Immediate Next Build Steps

1. Replace SQLite with Neon-ready Postgres models and migrations.
2. Introduce provider abstraction: `InboundProvider` and `ObjectStorage`.
3. Build mailbox and message domain model independent from Gmail.
4. Add catch-all Cloudflare worker prototype that writes raw MIME plus metadata.
5. Decide whether Cloudflare should write directly to Neon or call a single Render ingest endpoint.
6. Ship browser inbox UI before AI features.
7. Add deterministic OTP extraction before Groq.
8. Add Groq async assistant pane after message UX is stable and make it lazy, not automatic.

## Recommended Free-Tier Architecture

### Option A: keep Render as required backend

- Cloudflare Email Routing catch-all
- Cloudflare Email Worker
- optional Cloudflare Queue
- one Render free web service
- Neon free database
- R2 free tier for raw MIME
- Groq free tier for on-demand AI

This is the best fit if Render remains a hard requirement.

### Option B: safer free-tier hybrid

- Cloudflare handles ingress and raw storage
- Cloudflare writes directly to Neon
- Render serves inbox UI and read APIs
- AI is triggered manually by the user

This avoids depending on a sleeping Render service for mail receipt.

### Option C: strongest pure-free technical architecture

- Cloudflare Worker / Pages / R2 / Queue
- Neon for relational state
- no Render in MVP

This is probably the technically strongest free architecture, but it no longer follows the Render preference.

## Final Recommendation

The strongest path is:

- Cloudflare at the edge
- Render for app runtime if we keep a single free web service
- Neon for relational state
- R2 for raw email and attachments
- Groq as an async extraction layer used sparingly

The biggest product decision is not the AI model. It is whether we launch public inboxes or session-locked inboxes.

Choose session-locked inboxes first. That reduces abuse, legal exposure, and operational chaos while still delivering the core value of a modern temporary email product.
