"""Shared socket protocol limits and JSON boundary types."""

from typing import Any

# What json.loads can return. Decoded values are annotated with it so that
# isinstance narrowing yields dict[str, JsonValue] and list[JsonValue] rather
# than containers of unknown type.
type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
type JsonObject = dict[str, Any]

# Bound both request and response lines, including large browser-state snapshots.
MAX_MESSAGE = 8 * 1024 * 1024 + 65536
