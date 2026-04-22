Standalone tempmail application.

Purpose:
- create disposable mailboxes through a browser UI;
- receive inbound mail through Cloudflare Email Routing and an Email Worker;
- persist mailboxes and messages in Neon Postgres;
- extract OTP codes, action links, and summaries with deterministic parsing plus Groq;
- keep the older Gmail/Telegram path available as legacy code.

Current status:
- FastAPI app and browser UI are implemented;
- Render free web service is the current deployment target;
- Neon-backed tempmail schema is implemented;
- Cloudflare Email Worker scaffold is implemented under workers/email-ingest;
- Turnstile client config is exposed without leaking private secrets;
- test suite passes.

Files of interest:
- app/main.py              FastAPI/bootstrap entrypoint
- app/static/              browser UI assets
- app/config.py            env-based config
- app/db.py                SQLAlchemy schema init
- app/api/tempmail.py      tempmail API
- app/services/gmail_client.py
- app/services/telegram_client.py
- app/services/ingestion_service.py
- app/services/ai_service.py
- app/repositories/aliases.py
- app/repositories/inbound_messages.py
- app/repositories/deliveries.py
- workers/email-ingest/
- .env.example
- ARCHITECTURE.md
- DEPLOY.md
- requirements.txt
