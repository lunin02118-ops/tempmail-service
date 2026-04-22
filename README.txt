Standalone mail -> Telegram application.

Purpose:
- receive emails from Gmail API;
- detect which alias the email was sent to;
- map alias to Telegram chat;
- deliver the email into Telegram;
- remain fully independent from Hermes runtime.

Current status:
- isolated Gmail OAuth is already configured separately in this directory;
- standalone Python app scaffold is implemented;
- SQLite schema bootstrap is implemented;
- alias generation and alias routing logic are implemented;
- Gmail message normalization/ingestion service is implemented;
- Telegram client adapter is implemented;
- worker skeleton is implemented;
- test suite passes.

Files of interest:
- app/main.py              FastAPI/bootstrap entrypoint
- app/worker.py            polling worker loop
- app/config.py            env-based config
- app/db.py                SQLite schema init
- app/services/gmail_client.py
- app/services/telegram_client.py
- app/services/ingestion_service.py
- app/repositories/aliases.py
- app/repositories/inbound_messages.py
- app/repositories/deliveries.py
- .env.example
- ARCHITECTURE.md
- requirements.txt

Next required input from user:
- Telegram bot token
- one test chat_id

After that, the next implementation step is live Telegram delivery verification and wiring the worker to real polling in production mode.
