from __future__ import annotations

import quopri
import re


EMAIL_HEADER_MAX_CHARS = 4_096
EMAIL_BODY_MAX_CHARS = 131_072
EMAIL_RAW_PAYLOAD_MAX_CHARS = 65_536
EMAIL_ANALYSIS_BODY_MAX_CHARS = 20_000

_MOJIBAKE_MARKERS = (
    "Ð",
    "Ñ",
    "Â",
    "Ã",
    "â€",
    "â€™",
    "â€œ",
    "â€�",
    "â€“",
    "â€”",
    "â€¦",
)
_C1_CONTROL_RE = re.compile(r"[\x80-\x9f]")
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_QUOTED_PRINTABLE_RE = re.compile(r"=(?:\r?\n|[0-9A-F]{2})")
_UNSAFE_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _mojibake_score(value: str) -> int:
    marker_score = sum(value.count(marker) for marker in _MOJIBAKE_MARKERS) * 4
    control_score = len(_C1_CONTROL_RE.findall(value)) * 3
    replacement_score = value.count("�") * 3
    cyrillic_score = len(_CYRILLIC_RE.findall(value))
    return marker_score + control_score + replacement_score - cyrillic_score


def repair_mojibake(value: str | None) -> str | None:
    """Repair common UTF-8-as-Latin-1/CP1252 mojibake without touching clean text."""
    if value is None or value == "":
        return value

    text = str(value)
    if not any(marker in text for marker in _MOJIBAKE_MARKERS) and not _C1_CONTROL_RE.search(text):
        return text

    original_score = _mojibake_score(text)
    candidates = [text]
    for encoding in ("latin1", "cp1252"):
        try:
            candidates.append(text.encode(encoding).decode("utf-8"))
        except UnicodeError:
            continue

    best = min(candidates, key=_mojibake_score)
    if best != text and _mojibake_score(best) + 2 < original_score:
        return best
    return text


def decode_quoted_printable_text(value: str | None) -> str | None:
    if value is None or value == "":
        return value

    text = str(value)
    if not _QUOTED_PRINTABLE_RE.search(text):
        return text

    decoded_bytes = quopri.decodestring(text.encode("utf-8", errors="ignore"))
    try:
        return decoded_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return decoded_bytes.decode("latin-1", errors="ignore")


def sanitize_email_text(value: str | None, *, max_chars: int | None = None) -> str | None:
    if value is None or value == "":
        return value

    text = _UNSAFE_CONTROL_RE.sub("", str(value))
    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars]
    return text


def sanitize_email_header(value: str | None, *, max_chars: int = EMAIL_HEADER_MAX_CHARS) -> str | None:
    if value is None or value == "":
        return value

    repaired = repair_mojibake(value)
    return sanitize_email_text(repaired, max_chars=max_chars)


def sanitize_raw_payload_json(
    value: str | None,
    *,
    max_chars: int = EMAIL_RAW_PAYLOAD_MAX_CHARS,
) -> str | None:
    return sanitize_email_text(value, max_chars=max_chars)


def sanitize_json_payload(value: object, *, string_max_chars: int | None = EMAIL_BODY_MAX_CHARS) -> object:
    if isinstance(value, str):
        return sanitize_email_text(value, max_chars=string_max_chars) or ""
    if isinstance(value, list):
        return [sanitize_json_payload(item, string_max_chars=string_max_chars) for item in value]
    if isinstance(value, tuple):
        return [sanitize_json_payload(item, string_max_chars=string_max_chars) for item in value]
    if isinstance(value, dict):
        return {
            str(sanitize_email_text(str(key), max_chars=EMAIL_HEADER_MAX_CHARS) or ""): sanitize_json_payload(
                item,
                string_max_chars=string_max_chars,
            )
            for key, item in value.items()
        }
    return value


def normalize_email_content(value: str | None, *, max_chars: int | None = None) -> str | None:
    if value is None or value == "":
        return value

    normalized = sanitize_email_text(str(value)) or ""
    previous = None
    for _ in range(2):
        if normalized == previous:
            break
        previous = normalized
        normalized = decode_quoted_printable_text(normalized) or ""
        normalized = repair_mojibake(normalized) or ""
        normalized = sanitize_email_text(normalized) or ""
    return sanitize_email_text(normalized, max_chars=max_chars)
