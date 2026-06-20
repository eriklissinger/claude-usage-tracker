"""Typed transcript-domain models and weighting helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


def parse_timestamp(value: str | datetime) -> datetime:
    """Parse transcript timestamps into UTC-aware datetimes."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    return datetime.fromisoformat(candidate).astimezone(UTC)


class ModelFamily(str, Enum):
    """Canonical model-family buckets from the Swift core."""

    OPUS = "opus"
    SONNET = "sonnet"
    HAIKU = "haiku"
    UNKNOWN = "unknown"

    @classmethod
    def from_model(cls, model: str) -> ModelFamily:
        normalized = model.casefold()
        if "opus" in normalized:
            return cls.OPUS
        if "sonnet" in normalized:
            return cls.SONNET
        if "haiku" in normalized:
            return cls.HAIKU
        return cls.UNKNOWN

    @property
    def multiplier(self) -> float:
        if self is ModelFamily.OPUS:
            return 5.0
        if self is ModelFamily.HAIKU:
            return 0.25
        return 1.0


@dataclass(frozen=True, slots=True)
class UsageEntry:
    """One parsed assistant usage event from a transcript."""

    timestamp: datetime
    model: str
    project: str | None = None
    message_id: str | None = None
    request_id: str | None = None
    input_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0

    @classmethod
    def from_flat_record(
        cls,
        *,
        timestamp: str | datetime,
        model: str,
        tokens: int,
        project: str | None = None,
        message_id: str | None = None,
        request_id: str | None = None,
    ) -> UsageEntry:
        return cls(
            timestamp=parse_timestamp(timestamp),
            model=model,
            project=project,
            message_id=message_id,
            request_id=request_id,
            input_tokens=tokens,
        )

    @classmethod
    def from_usage(
        cls,
        *,
        timestamp: str | datetime,
        model: str,
        project: str | None = None,
        message_id: str | None = None,
        request_id: str | None = None,
        input_tokens: int = 0,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        output_tokens: int = 0,
    ) -> UsageEntry:
        return cls(
            timestamp=parse_timestamp(timestamp),
            model=model,
            project=project,
            message_id=message_id,
            request_id=request_id,
            input_tokens=input_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
            output_tokens=output_tokens,
        )

    @property
    def dedup_key(self) -> tuple[str, str] | None:
        if not self.message_id or not self.request_id:
            return None
        return (self.message_id, self.request_id)

    @property
    def family(self) -> ModelFamily:
        return ModelFamily.from_model(self.model)

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
            + self.output_tokens
        )

    @property
    def ncu(self) -> float:
        base = (
            self.input_tokens
            + (self.cache_creation_tokens * 1.25)
            + (self.cache_read_tokens * 0.0)
            + (self.output_tokens * 5.0)
        )
        return base * self.family.multiplier


@dataclass(frozen=True, slots=True)
class UsageSummary:
    """Aggregate totals across a set of usage entries."""

    entry_count: int
    total_tokens: int
    total_ncu: float


@dataclass(frozen=True, slots=True)
class BreakdownRow:
    """Display-friendly grouped usage totals."""

    label: str
    ncu: float
    share: float
    entry_count: int
    family: ModelFamily | None = None


@dataclass(frozen=True, slots=True)
class UsageBlock:
    """A 5-hour anchored transcript block."""

    started_at: datetime
    ends_at: datetime
    last_entry_at: datetime
    entries: tuple[UsageEntry, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class UsageWeek:
    """A 7-day transcript-derived usage window."""

    started_at: datetime
    ends_at: datetime
    entries: tuple[UsageEntry, ...] = field(default_factory=tuple)
