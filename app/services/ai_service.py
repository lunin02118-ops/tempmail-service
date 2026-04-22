from __future__ import annotations

import json
import re
from email.utils import parseaddr
from itertools import count
from typing import Any

import httpx

from app.config import AppSettings


_URL_RE = re.compile(r"https?://[^\s<>\"]+")
_OTP_CONTEXT_RE = re.compile(
    r"(?:otp|code|passcode|verification|security code|confirm(?:ation)? code)[^0-9]{0,20}([0-9]{4,10})",
    re.IGNORECASE,
)
_OTP_FALLBACK_RE = re.compile(r"\b([0-9]{4,8})\b")


def _compact_text(*parts: str | None) -> str:
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def _extract_action_links(text: str) -> list[str]:
    matches = _URL_RE.findall(text)
    seen: set[str] = set()
    result: list[str] = []
    for match in matches:
        if match not in seen:
            seen.add(match)
            result.append(match)
    return result[:5]


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


def _extract_otp_code(text: str) -> tuple[str | None, str]:
    contextual_match = _OTP_CONTEXT_RE.search(text)
    if contextual_match:
        return contextual_match.group(1), "high"

    fallback_match = _OTP_FALLBACK_RE.search(text)
    if fallback_match:
        return fallback_match.group(1), "medium"

    return None, "low"


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
        subject = str(message.get("subject") or "").strip()
        body_text = str(message.get("body_text") or "").strip()
        body_html = str(message.get("body_html") or "").strip()
        from_address = str(message.get("from_address") or "").strip() or None
        combined_text = _compact_text(subject, body_text, body_html)
        otp_code, confidence = _extract_otp_code(combined_text)
        message_type = _detect_message_type(combined_text)
        action_links = _extract_action_links(combined_text)
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
        if not allow_remote or not self._settings.groq_api_keys:
            return deterministic

        prompt = json.dumps(
            {
                "mailbox_address": message.get("mailbox_address"),
                "from_address": message.get("from_address"),
                "subject": message.get("subject"),
                "body_text": message.get("body_text"),
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

        return {
            "provider": "groq",
            "model": self._settings.groq_model,
            "status": "completed",
            "summary": str(groq_payload.get("summary") or deterministic.get("summary") or ""),
            "message_type": str(groq_payload.get("message_type") or deterministic.get("message_type") or ""),
            "otp_code": str(groq_payload.get("otp_code") or deterministic.get("otp_code") or "") or None,
            "action_required": str(groq_payload.get("action_required") or deterministic.get("action_required") or "")
            or None,
            "action_links_json": json.dumps([str(item) for item in action_links][:5]),
            "sender_brand": str(groq_payload.get("sender_brand") or deterministic.get("sender_brand") or "") or None,
            "confidence": str(groq_payload.get("confidence") or deterministic.get("confidence") or ""),
            "error_text": None,
        }
