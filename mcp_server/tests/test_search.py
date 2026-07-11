"""Tests for search.SearchEngine argument handling.

DB and OpenAI are mocked — these tests verify argument clamping, empty-query
short-circuit, and the SQL surface. Live-DB behavior is out of scope (and
would require a docker-compose fixture the project has deliberately
anti-scoped for S0).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hindsight_mcp.search import MAX_K, SearchEngine


def _engine_with_fake_pool() -> SearchEngine:
    # Instantiate without calling __init__ so we can attach fakes and
    # avoid touching the real pool/OpenAI constructors.
    engine = SearchEngine.__new__(SearchEngine)
    engine._openai = MagicMock()
    engine._openai.embeddings.create.return_value = MagicMock(data=[MagicMock(embedding=[0.0] * 1536)])
    engine._pool = MagicMock()

    cursor = MagicMock()
    cursor.fetchall.return_value = []
    cm_cursor = MagicMock()
    cm_cursor.__enter__.return_value = cursor
    cm_cursor.__exit__.return_value = False

    conn = MagicMock()
    conn.cursor.return_value = cm_cursor
    cm_conn = MagicMock()
    cm_conn.__enter__.return_value = conn
    cm_conn.__exit__.return_value = False

    engine._pool.connection.return_value = cm_conn
    return engine


def test_empty_query_returns_empty_without_calling_openai() -> None:
    engine = _engine_with_fake_pool()
    assert engine.search("") == []
    assert engine.search("   ") == []
    engine._openai.embeddings.create.assert_not_called()


def test_k_is_clamped_to_max() -> None:
    engine = _engine_with_fake_pool()
    engine.search("anything", k=10_000)
    cursor = engine._pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    _, params = cursor.execute.call_args[0]
    assert params["k"] == MAX_K


def test_k_is_clamped_to_one_minimum() -> None:
    engine = _engine_with_fake_pool()
    engine.search("anything", k=0)
    cursor = engine._pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    _, params = cursor.execute.call_args[0]
    assert params["k"] == 1


def test_source_filter_parameterized_not_interpolated() -> None:
    engine = _engine_with_fake_pool()
    # A hostile source value should remain parameterized and never reach
    # the SQL string — protects against injection regressions if the
    # WHERE clause construction gets edited later.
    engine.search("q", source="claude'; drop table items;--")
    cursor = engine._pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    sql, params = cursor.execute.call_args[0]
    assert "drop table" not in sql
    assert "claude'; drop table items;--" in params.values()


def test_ping_returns_true_on_success() -> None:
    engine = _engine_with_fake_pool()
    assert engine.ping() is True


def test_ping_returns_false_on_exception() -> None:
    engine = _engine_with_fake_pool()
    engine._pool.connection.side_effect = Exception("pool broken")
    assert engine.ping() is False


def test_no_source_omits_source_filter() -> None:
    engine = _engine_with_fake_pool()
    engine.search("q")
    cursor = engine._pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    sql, params = cursor.execute.call_args[0]
    assert "and i.source = %(source)s" not in sql
    assert "source" not in params


def test_source_adds_and_clause() -> None:
    engine = _engine_with_fake_pool()
    engine.search("q", source="chatgpt")
    cursor = engine._pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    sql, params = cursor.execute.call_args[0]
    assert "and i.source = %(source)s" in sql
    assert params["source"] == "chatgpt"


def test_hybrid_sql_has_both_signals() -> None:
    engine = _engine_with_fake_pool()
    engine.search("q")
    cursor = engine._pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    sql, _ = cursor.execute.call_args[0]
    assert "vector_hits" in sql
    assert "lexical_hits" in sql
    assert "websearch_to_tsquery" in sql
    assert "rrf_score" in sql
