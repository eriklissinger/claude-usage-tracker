"""Transcript JSONL parsing helpers."""

from __future__ import annotations

import json
from typing import Any

from .models import UsageEntry


def parse_transcript_line(line: str) -> UsageEntry | None:
    """Parse one transcript line into a usage entry, if valid."""
    candidate = line.strip()
    if not candidate:
        return None

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    role = payload.get("role", payload.get("type"))
    if role != "assistant":
        return None

    model = _extract_model(payload)
    if not model or model == "<synthetic>":
        return None

    timestamp = payload.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp:
        return None

    message_id = _optional_string(payload.get("messageId"))
    request_id = _optional_string(payload.get("requestId"))
    project = _optional_string(payload.get("project", payload.get("cwd")))

    flat_tokens = payload.get("tokens")
    if isinstance(flat_tokens, int) and not isinstance(flat_tokens, bool) and flat_tokens >= 0:
        return UsageEntry.from_flat_record(
            timestamp=timestamp,
            model=model,
            project=project,
            tokens=flat_tokens,
            message_id=message_id,
            request_id=request_id,
        )

    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None

    return UsageEntry.from_usage(
        timestamp=timestamp,
        model=model,
        project=project,
        message_id=message_id,
        request_id=request_id,
        input_tokens=_usage_int(usage, "input_tokens", "inputTokens"),
        cache_creation_tokens=_usage_int(
            usage,
            "cache_creation_input_tokens",
            "cacheCreationInputTokens",
            "cache_creation_tokens",
            "cacheCreationTokens",
        ),
        cache_read_tokens=_usage_int(
            usage,
            "cache_read_input_tokens",
            "cacheReadInputTokens",
            "cache_read_tokens",
            "cacheReadTokens",
        ),
        output_tokens=_usage_int(usage, "output_tokens", "outputTokens"),
    )


def _extract_model(payload: dict[str, Any]) -> str | None:
    direct_model = payload.get("model")
    if isinstance(direct_model, str):
        return direct_model

    message = payload.get("message")
    if isinstance(message, dict):
        nested_model = message.get("model")
        if isinstance(nested_model, str):
            return nested_model
    return None


def _usage_int(usage: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if value is None:
            continue
        if _is_non_negative_int(value):
            return value
        return 0
    return 0


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
