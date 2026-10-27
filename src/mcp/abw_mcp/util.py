"""Shared helpers for ABW MCP."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_H1_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


def canonical_json(value: Any) -> str:
    """Serialize data into stable compact JSON."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_json(value: Any) -> str:
    """Return the SHA-256 of a canonical JSON payload."""

    payload = canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compact_json(value: Any) -> str:
    """Serialize JSON compactly for tool output."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def first_markdown_h1(content: str, fallback: str) -> str:
    """Extract the first markdown H1."""

    match = _H1_PATTERN.search(content)
    return match.group(1).strip() if match else fallback


def slugify(value: str) -> str:
    """Slugify a counterparty or identifier."""

    lowered = value.strip().lower()
    slug = _SLUG_PATTERN.sub("-", lowered).strip("-")
    return slug or "unknown"

