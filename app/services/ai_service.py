from __future__ import annotations

import html
import json
import quopri
import re
from email.utils import parseaddr
from itertools import count
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx

from app.config import AppSettings


_URL_RE = re.compile(r"https?://[^\s<>\"]+")
_HTML_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_OTP_CONTEXT_RE = re.compile(
    (
        r"(?:otp|passcode|verification|security code|confirm(?:ation)? code|"
        r"verification code|one-time password|временн\w+\s+код|код(?:\s+подтверждения)?|"
        r"проверочн\w+\s+код|код\s+безопасности)"
        r"[^0-9]{0,40}([0-9][0-9\s-]{3,14}[0-9])"
    ),
    re.IGNORECASE,
)
_OTP_FALLBACK_RE = re.compile(r"\b((?:[0-9][\s-]?){4,10})\b")
_QUOTED_PRINTABLE_RE = re.compile(r"=(?:\r?\n|[0-9A-F]{2})")
_HTML_BREAK_RE = re.compile(r"(?i)<br\s*/?>")
_HTML_BLOCK_CLOSE_RE = re.compile(r"(?i)</(?:p|div|tr|table|li|h[1-6]|section|article)>")
_HTML_TAG_RE = re.compile(r"(?s)<[^>]+>")

_ASSET_PATH_MARKERS = (
    "/fonts/",
    "/logo-assets/",
    "/images/",
    "/image/",
    "/static/",
    "/assets/",
    "/wf/open",
)
_TRACKING_HOST_SUFFIXES = (
    "mandrillapp.com",
    "sendgrid.net",
)
_TRACKING_PATH_MARKERS = (
    "/track/click",
    "/wf/open",
    "/open?",
)
_ASSET_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".css",
    ".js",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
)


def _compact_text(*parts: str | None) -> str:
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def _decode_quoted_printable_text(value: str | None) -> str:
    if not value:
        return ""
    text = value.strip()
    if not text:
        return ""
    if not _QUOTED_PRINTABLE_RE.search(text):
        return text
    decoded_bytes = quopri.decodestring(text.encode("utf-8", errors="ignore"))
    try:
        return decoded_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return decoded_bytes.decode("latin-1", errors="ignore")


def _strip_html_to_text(value: str | None) -> str:
    if not value:
        return ""
    text = _HTML_TAG_RE.sub(" ", _HTML_BLOCK_CLOSE_RE.sub("\n", _HTML_BREAK_RE.sub("\n", value)))
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_candidate_url(value: str) -> str | None:
    candidate = html.unescape(value.strip()).rstrip(").,;:!?\"'")
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    lowered = candidate.lower()
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if host == "cdn.openai.com":
        return None
    if any(host == suffix or host.endswith(f".{suffix}") for suffix in _TRACKING_HOST_SUFFIXES):
        return None
    if any(marker in path for marker in _TRACKING_PATH_MARKERS):
        return None
    if any(marker in lowered for marker in _ASSET_PATH_MARKERS):
        return None
    if path.endswith(_ASSET_EXTENSIONS):
        return None
    return candidate


def _sanitize_action_links(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = _normalize_candidate_url(str(value))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result[:5]


def _extract_action_links(text: str, html_text: str | None = None) -> list[str]:
    matches = list(_URL_RE.findall(text))
    if html_text:
        matches.extend(_HTML_HREF_RE.findall(html_text))
    return _sanitize_action_links(matches)


def _extract_sender_brand(from_address: str | None) -> str | None:
    if not from_address:
        return None
    _, parsed_address = parseaddr(from_address)
    address = parsed_address or from_address
    if "@" not in address:
        return None
    domain = address.split("@", 1)[1].lower().strip()
    parts = [part for part in domain.split(".") if part]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else None


def _detect_message_type(text: str) -> str:
    lowered = text.lower()
    if any(keyword in lowered for keyword in ("verify", "verification", "one-time password", "otp", "passcode")):
        return "verification"
    if any(
        keyword in lowered
        for keyword in ("reset password", "reset your password", "password reset", "recover account")
    ):
        return "password_reset"
    if any(keyword in lowered for keyword in ("sign in", "login", "log in")):
        return "login"
    if any(keyword in lowered for keyword in ("invoice", "receipt", "payment")):
        return "billing"
    return "general"


def _detect_action_required(text: str, message_type: str) -> str | None:
    lowered = text.lower()
    if "click the link" in lowered or "open the link" in lowered:
        return "Open the verification link"
    if message_type == "verification":
        return "Use the verification code"
    if message_type == "password_reset":
        return "Reset the password"
    if message_type == "login":
        return "Confirm the login"
    return None


def _build_summary(subject: str | None, body_text: str | None, otp_code: str | None) -> str:
    if otp_code:
        return f"Verification code detected: {otp_code}"
    if subject and subject.strip():
        return subject.strip()
    if body_text and body_text.strip():
        compact = " ".join(body_text.strip().split())
        return compact[:160]
    return "Email received"


def _normalize_otp_match(raw_match: str) -> str | None:
    digits_only = re.sub(r"\D", "", raw_match or "")
    if 4 <= len(digits_only) <= 10:
        return digits_only
    return None


def _otp_preference_key(code: str, source: str, index: int) -> tuple[int, int, int]:
    preferred_length_penalty = 0 if 6 <= len(code) <= 8 else 1
    source_penalty = 0 if source == "context" else 1
    return (source_penalty, preferred_length_penalty, index)


def _extract_otp_code(text: str) -> tuple[str | None, str]:
    candidates: list[tuple[str, str, int]] = []

    for match in _OTP_CONTEXT_RE.finditer(text):
        normalized = _normalize_otp_match(match.group(1))
        if normalized:
            candidates.append((normalized, "context", match.start()))

    for match in _OTP_FALLBACK_RE.finditer(text):
        normalized = _normalize_otp_match(match.group(1))
        if normalized:
            candidates.append((normalized, "fallback", match.start()))

    if candidates:
        best_code, best_source, _ = min(candidates, key=lambda item: _otp_preference_key(*item))
        return best_code, "high" if best_source == "context" else "medium"

    return None, "low"


def _prepare_analysis_content(message: dict[str, object]) -> dict[str, str | None]:
    subject = str(message.get("subject") or "").strip()
    body_text = _decode_quoted_printable_text(str(message.get("body_text") or ""))
    body_html = _decode_quoted_printable_text(str(message.get("body_html") or ""))
    visible_html_text = _strip_html_to_text(body_html)
    analysis_body = body_text or visible_html_text
    combined_text = _compact_text(subject, analysis_body)
    return {
        "subject": subject,
        "body_text": body_text,
        "body_html": body_html,
        "visible_html_text": visible_html_text,
        "analysis_body": analysis_body,
        "combined_text": combined_text,
    }


def _coerce_json_object(raw_text: str) -> dict[str, Any] | None:
    candidate = raw_text.strip()
    try:
        loaded = json.loads(candidate)
        return loaded if isinstance(loaded, dict) else None
    except json.JSONDecodeError:
        pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        loaded = json.loads(candidate[start : end + 1])
        return loaded if isinstance(loaded, dict) else None
    except json.JSONDecodeError:
        return None


class GroqKeyRotator:
    def __init__(self, api_keys: tuple[str, ...]) -> None:
        self._api_keys = list(api_keys)
        self._disabled_indexes: set[int] = set()
        self._counter = count()

    def _next_index(self) -> int | None:
        available_indexes = [index for index in range(len(self._api_keys)) if index not in self._disabled_indexes]
        if not available_indexes:
            return None
        return available_indexes[next(self._counter) % len(available_indexes)]

    async def complete_json(self, *, model: str, prompt: str) -> dict[str, Any] | None:
        max_attempts = len(self._api_keys)
        for _ in range(max_attempts):
            index = self._next_index()
            if index is None:
                return None

            api_key = self._api_keys[index]
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "temperature": 0.1,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "Extract email insights and respond with one JSON object only. "
                                    "Keys: summary, message_type, otp_code, action_required, action_links, sender_brand, confidence."
                                ),
                            },
                            {"role": "user", "content": prompt},
                        ],
                    },
                )

            if response.status_code == 401:
                self._disabled_indexes.add(index)
                continue

            if response.status_code in {429, 500, 502, 503, 504}:
                continue

            response.raise_for_status()
            payload = response.json()
            choices = payload.get("choices") or []
            if not choices:
                return None
            content = choices[0].get("message", {}).get("content")
            if not isinstance(content, str):
                return None
            return _coerce_json_object(content)

        return None


class MessageAnalysisService:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._groq_rotator = GroqKeyRotator(settings.groq_api_keys)

    def analyze_deterministically(self, message: dict[str, object]) -> dict[str, object | None]:
        prepared = _prepare_analysis_content(message)
        subject = str(prepared["subject"] or "").strip()
        body_text = str(prepared["analysis_body"] or "").strip()
        body_html = str(prepared["body_html"] or "").strip()
        from_address = str(message.get("from_address") or "").strip() or None
        combined_text = str(prepared["combined_text"] or "")
        otp_code, confidence = _extract_otp_code(combined_text)
        message_type = _detect_message_type(combined_text)
        action_links = _extract_action_links(body_text, body_html)
        sender_brand = _extract_sender_brand(from_address)
        action_required = _detect_action_required(combined_text, message_type)
        summary = _build_summary(subject, body_text, otp_code)

        return {
            "provider": "deterministic",
            "model": None,
            "status": "completed",
            "summary": summary,
            "message_type": message_type,
            "otp_code": otp_code,
            "action_required": action_required,
            "action_links_json": json.dumps(action_links),
            "sender_brand": sender_brand,
            "confidence": confidence,
            "error_text": None,
        }

    async def analyze_message(
        self,
        message: dict[str, object],
        *,
        allow_remote: bool = True,
    ) -> dict[str, object | None]:
        deterministic = self.analyze_deterministically(message)
        prepared = _prepare_analysis_content(message)
        if not allow_remote or not self._settings.groq_api_keys:
            return deterministic

        prompt = json.dumps(
            {
                "mailbox_address": message.get("mailbox_address"),
                "from_address": message.get("from_address"),
                "subject": prepared.get("subject"),
                "body_text": prepared.get("analysis_body"),
                "deterministic": {
                    "summary": deterministic.get("summary"),
                    "message_type": deterministic.get("message_type"),
                    "otp_code": deterministic.get("otp_code"),
                    "action_required": deterministic.get("action_required"),
                    "action_links": json.loads(str(deterministic.get("action_links_json") or "[]")),
                    "sender_brand": deterministic.get("sender_brand"),
                    "confidence": deterministic.get("confidence"),
                },
            },
            ensure_ascii=False,
        )

        try:
            groq_payload = await self._groq_rotator.complete_json(model=self._settings.groq_model, prompt=prompt)
        except httpx.HTTPError as exc:
            deterministic["error_text"] = str(exc)
            return deterministic

        if not groq_payload:
            return deterministic

        action_links = groq_payload.get("action_links")
        if not isinstance(action_links, list):
            action_links = json.loads(str(deterministic.get("action_links_json") or "[]"))
        action_links = _sanitize_action_links(str(item) for item in action_links)

        return {
            "provider": "groq",
            "model": self._settings.groq_model,
            "status": "completed",
            "summary": str(groq_payload.get("summary") or deterministic.get("summary") or ""),
            "message_type": str(groq_payload.get("message_type") or deterministic.get("message_type") or ""),
            "otp_code": str(groq_payload.get("otp_code") or deterministic.get("otp_code") or "") or None,
            "action_required": str(groq_payload.get("action_required") or deterministic.get("action_required") or "")
            or None,
            "action_links_json": json.dumps(action_links),
            "sender_brand": str(groq_payload.get("sender_brand") or deterministic.get("sender_brand") or "") or None,
            "confidence": str(groq_payload.get("confidence") or deterministic.get("confidence") or ""),
            "error_text": None,
        }
