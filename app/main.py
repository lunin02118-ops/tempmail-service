from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from app.api.admin_archive import router as admin_archive_router
from app.api.aliases import router as aliases_router
from app.api.tempmail import router as tempmail_router
from app.api.telegram import router as telegram_router, set_telegram_client_dependency
from app.config import AppSettings
from app.db import initialize_database
from app.worker import process_gmail_tempmail_once, run_worker_loop


logger = logging.getLogger(__name__)


def _ensure_writable_gmail_token(settings: AppSettings) -> None:
    if not settings.gmail_token_path:
        return
    target = Path(settings.gmail_token_path)
    if target.exists() and target.stat().st_size > 0:
        return
    seed = settings.gmail_token_seed_path
    if not seed:
        return
    seed_path = Path(seed)
    if not seed_path.exists():
        logger.warning("gmail token seed missing: %s", seed_path)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(seed_path, target)
    try:
        target.chmod(0o600)
    except OSError:
        pass
    logger.info("seeded writable gmail token at %s from %s", target, seed_path)


async def _gmail_tempmail_polling_loop(settings: AppSettings) -> None:
    interval = max(int(settings.gmail_poll_seconds or 60), 15)
    logger.info("gmail tempmail in-process polling started (interval=%ss)", interval)
    while True:
        try:
            result = await asyncio.to_thread(process_gmail_tempmail_once, settings)
            if result.get("processed"):
                logger.info("gmail tempmail poll: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("gmail tempmail poll iteration failed")
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise


def create_app(telegram_client=None) -> FastAPI:
    settings = AppSettings.from_env()
    initialize_database(settings)
    set_telegram_client_dependency(telegram_client)
    _ensure_writable_gmail_token(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        background_tasks: list[asyncio.Task] = []
        if settings.has_gmail_tempmail_ingest and settings.gmail_tempmail_in_process:
            task = asyncio.create_task(
                _gmail_tempmail_polling_loop(settings),
                name="gmail-tempmail-polling",
            )
            background_tasks.append(task)
        try:
            yield
        finally:
            for task in background_tasks:
                task.cancel()
            for task in background_tasks:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    app = FastAPI(title="samgpt-tempmail", lifespan=lifespan)
    static_dir = settings.project_root / "app" / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(admin_archive_router)
    app.include_router(aliases_router)
    app.include_router(tempmail_router)
    app.include_router(telegram_router)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def web_app() -> HTMLResponse:
        index_path = static_dir / "index.html"
        return HTMLResponse(index_path.read_text(encoding="utf-8"))

    @app.get("/widget", response_class=HTMLResponse, include_in_schema=False)
    def desktop_widget() -> HTMLResponse:
        widget_path = static_dir / "widget.html"
        return HTMLResponse(widget_path.read_text(encoding="utf-8"))

    @app.get("/admin/archive", response_class=HTMLResponse, include_in_schema=False)
    def admin_archive() -> HTMLResponse:
        archive_path = static_dir / "archive.html"
        return HTMLResponse(archive_path.read_text(encoding="utf-8"))

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def web_manifest() -> FileResponse:
        return FileResponse(static_dir / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/service-worker.js", include_in_schema=False)
    def service_worker() -> FileResponse:
        return FileResponse(static_dir / "service-worker.js", media_type="application/javascript")

    @app.get("/client-config")
    def client_config() -> dict[str, object]:
        turnstile_enabled = settings.turnstile_enabled and bool(settings.turnstile_secret_key)
        return {
            "mail_domain": settings.active_mail_domain,
            "mail_domains": list(settings.available_mail_domains),
            "mailbox_default_ttl_minutes": settings.mailbox_default_ttl_minutes,
            "turnstile_site_key": settings.turnstile_site_key if turnstile_enabled else None,
            "turnstile_enabled": turnstile_enabled,
            "shared_inbox_enabled": bool(settings.gmail_tempmail_address),
            "shared_inbox_address": settings.gmail_tempmail_address or None,
        }

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "samgpt-tempmail"}

    return app


def run_api_server() -> None:
    settings = AppSettings.from_env()
    initialize_database(settings)
    uvicorn.run(
        create_app(),
        host=settings.app_host,
        port=settings.app_port,
        log_level=settings.log_level.lower(),
    )


def run_all_in_one() -> None:
    worker_thread = threading.Thread(target=run_worker_loop, name="mail-telegram-worker", daemon=True)
    worker_thread.start()
    run_api_server()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["api", "worker", "all-in-one"], default="all-in-one")
    args = parser.parse_args()

    if args.mode == "worker":
        run_worker_loop()
    elif args.mode == "api":
        run_api_server()
    else:
        run_all_in_one()
