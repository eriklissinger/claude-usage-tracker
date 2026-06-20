"""Shared validation helpers for fixture-suite tests."""

from __future__ import annotations

import json
from pathlib import Path


def _assert_non_empty_text(path: Path, label: str) -> None:
    content = path.read_text(encoding="utf-8")
    assert content.strip(), f"empty fixture member: {label}"


def _assert_json(path: Path, label: str) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload is not None, f"invalid JSON fixture: {label}"


def _assert_jsonl(path: Path, label: str) -> None:
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert lines, f"empty JSONL fixture: {label}"
    for line in lines:
        assert json.loads(line) is not None, f"invalid JSONL record: {label}"


def assert_fixture_member(path: Path, label: str) -> None:
    assert path.exists(), f"missing fixture member: {label}"

    if path.suffix == ".json":
        _assert_json(path, label)
    elif path.suffix == ".jsonl":
        _assert_jsonl(path, label)
    else:
        _assert_non_empty_text(path, label)


def assert_fixture_suite(base_dir: Path, suite: str, members: tuple[str, ...]) -> None:
    suite_path = base_dir / suite
    assert suite_path.exists(), f"missing fixture suite: {suite}"

    if suite_path.is_file():
        assert_fixture_member(suite_path, suite)
        return

    for member in members:
        member_path = suite_path / member
        assert_fixture_member(member_path, f"{suite}/{member}")
