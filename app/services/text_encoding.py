from __future__ import annotations

import re


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
