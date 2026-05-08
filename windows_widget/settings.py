from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

APP_NAME = "SamGPTDesktopWidget"
DEFAULT_WIDGET_URL = "https://tempmail-web.onrender.com/widget"
MIN_WIDGET_WIDTH = 360
MIN_WIDGET_HEIGHT = 430
PERSISTED_SETTING_KEYS = (
    "url",
    "width",
    "height",
    "x",
    "y",
    "always_on_top",
    "pin_desktop",
    "hide_from_taskbar",
)


@dataclass(slots=True)
class WidgetSettings:
    url: str = DEFAULT_WIDGET_URL
    width: int = 420
    height: int = 540
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

    if not isinstance(payload, dict):
        return {}

    return {key: payload[key] for key in PERSISTED_SETTING_KEYS if key in payload}


def save_settings(settings: WidgetSettings, path: Path | None = None) -> Path:
    target = path or settings_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    persisted_payload = {key: asdict(settings)[key] for key in PERSISTED_SETTING_KEYS}
    target.write_text(json.dumps(persisted_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def resolve_settings(saved: dict[str, Any], overrides: dict[str, Any]) -> WidgetSettings:
    merged = asdict(WidgetSettings())
    merged.update({key: value for key, value in saved.items() if key in merged})
    merged.update({key: value for key, value in overrides.items() if key in merged and value is not None})
    merged["width"] = max(int(merged["width"]), MIN_WIDGET_WIDTH)
    merged["height"] = max(int(merged["height"]), MIN_WIDGET_HEIGHT)
    merged["url"] = normalize_widget_url(str(merged["url"]))
    return WidgetSettings(**merged)
