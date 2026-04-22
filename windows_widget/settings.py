from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

APP_NAME = "SamGPTDesktopWidget"
DEFAULT_WIDGET_URL = "https://tempmail-web.onrender.com/widget"


@dataclass(slots=True)
class WidgetSettings:
    url: str = DEFAULT_WIDGET_URL
    width: int = 430
    height: int = 900
    x: int | None = None
    y: int | None = None
    always_on_top: bool = False
    pin_desktop: bool = False
    hide_from_taskbar: bool = True
    debug: bool = False
    close_after: float = 0.0


def appdata_root() -> Path:
    candidate = os.getenv("APPDATA")
    if candidate:
        return Path(candidate)
    return Path.home() / "AppData" / "Roaming"


def settings_directory() -> Path:
    return appdata_root() / "TempmailWidget"


def settings_file() -> Path:
    return settings_directory() / "settings.json"


def webview_storage_dir() -> Path:
    return settings_directory() / "webview"


def normalize_widget_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("native", "1")
    return urlunparse(parsed._replace(query=urlencode(query)))


def load_saved_settings(path: Path | None = None) -> dict[str, Any]:
    target = path or settings_file()
    if not target.exists():
        return {}

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def save_settings(settings: WidgetSettings, path: Path | None = None) -> Path:
    target = path or settings_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def resolve_settings(saved: dict[str, Any], overrides: dict[str, Any]) -> WidgetSettings:
    merged = asdict(WidgetSettings())
    merged.update({key: value for key, value in saved.items() if key in merged})
    merged.update({key: value for key, value in overrides.items() if key in merged and value is not None})
    merged["url"] = normalize_widget_url(str(merged["url"]))
    return WidgetSettings(**merged)
