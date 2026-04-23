from __future__ import annotations

import argparse
import threading

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
from app.worker import run_worker_loop


def create_app(telegram_client=None) -> FastAPI:
    settings = AppSettings.from_env()
    initialize_database(settings)
    set_telegram_client_dependency(telegram_client)

    app = FastAPI(title="samgpt-tempmail")
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
        return {
            "mail_domain": settings.active_mail_domain,
            "mail_domains": list(settings.available_mail_domains),
            "mailbox_default_ttl_minutes": settings.mailbox_default_ttl_minutes,
            "turnstile_site_key": settings.turnstile_site_key,
            "turnstile_enabled": bool(settings.turnstile_secret_key),
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
