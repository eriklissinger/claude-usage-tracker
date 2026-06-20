"""Aggregation and grouped breakdown helpers for transcript usage."""

from __future__ import annotations

from pathlib import PurePath

from .models import BreakdownRow, ModelFamily, UsageEntry, UsageSummary

FAMILY_ORDER = [ModelFamily.OPUS, ModelFamily.SONNET, ModelFamily.HAIKU, ModelFamily.UNKNOWN]


def aggregate_entries(entries: list[UsageEntry]) -> UsageSummary:
    """Summarize total tokens and weighted NCU."""
    return UsageSummary(
        entry_count=len(entries),
        total_tokens=sum(entry.total_tokens for entry in entries),
        total_ncu=sum(entry.ncu for entry in entries),
    )


def model_breakdown(entries: list[UsageEntry]) -> list[BreakdownRow]:
    """Group transcript usage into the canonical model-family order."""
    total_ncu = sum(entry.ncu for entry in entries)
    grouped: dict[ModelFamily, tuple[int, float]] = {}
    for entry in entries:
        entry_count, ncu = grouped.get(entry.family, (0, 0.0))
        grouped[entry.family] = (entry_count + 1, ncu + entry.ncu)

    rows: list[BreakdownRow] = []
    for family in FAMILY_ORDER:
        if family not in grouped:
            continue
        entry_count, ncu = grouped[family]
        rows.append(
            BreakdownRow(
                label=family.value,
                ncu=ncu,
                share=(ncu / total_ncu) if total_ncu else 0.0,
                entry_count=entry_count,
                family=family,
            )
        )
    return rows


def project_breakdown(entries: list[UsageEntry], limit: int = 3) -> list[BreakdownRow]:
    """Group transcript usage by project basename and return the top rows."""
    total_ncu = sum(entry.ncu for entry in entries)
    grouped: dict[str, tuple[int, float]] = {}
    for entry in entries:
        label = _project_label(entry.project)
        entry_count, ncu = grouped.get(label, (0, 0.0))
        grouped[label] = (entry_count + 1, ncu + entry.ncu)

    rows = [
        BreakdownRow(
            label=label,
            ncu=ncu,
            share=(ncu / total_ncu) if total_ncu else 0.0,
            entry_count=entry_count,
        )
        for label, (entry_count, ncu) in grouped.items()
    ]
    rows.sort(key=lambda row: (-row.ncu, row.label))
    return rows[:limit]


def _project_label(project: str | None) -> str:
    if not project:
        return "unknown"
    name = PurePath(project).name
    return name or "unknown"
