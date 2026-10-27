"""Runtime service wiring for ABW MCP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Settings


@dataclass(slots=True)
class RuntimeServices:
    """Shared services for request handlers."""

    settings: Settings
    audit: Any
    data: Any
    obo: Any | None = None

