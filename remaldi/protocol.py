"""Shared socket protocol limits and JSON object boundary types."""

from typing import Any

type JsonObject = dict[str, Any]

# Bound both request and response lines, including large browser-state snapshots.
MAX_MESSAGE = 8 * 1024 * 1024 + 65536
