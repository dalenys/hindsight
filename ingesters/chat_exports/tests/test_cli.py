"""Tests for the CLI's non-empty-database guard.

`--mode=replace` deletes a source's rows before inserting. Against a
populated database (e.g. the backfill-owned live Substrate 1 corpus)
that is destructive, so replace-mode is refused unless the operator
passes --allow-nonempty. Fresh installs (empty `items`) are never
blocked. The decision is a pure predicate so it can be tested without
a live Postgres.
"""

from __future__ import annotations

from chat_ingester import cli


def test_replace_blocked_on_nonempty_without_flag() -> None:
    assert cli._replace_blocked(item_count=42, mode="replace", allow_nonempty=False) is True


def test_replace_allowed_on_empty_db() -> None:
    assert cli._replace_blocked(item_count=0, mode="replace", allow_nonempty=False) is False


def test_replace_allowed_when_flag_passed() -> None:
    assert cli._replace_blocked(item_count=42, mode="replace", allow_nonempty=True) is False


def test_append_never_blocked() -> None:
    assert cli._replace_blocked(item_count=42, mode="append", allow_nonempty=False) is False
