"""Postgres availability for integration tests.

Tests that execute real SQL import `requires_postgres` and skip when the
database is unreachable, so the unit suite still runs on a laptop with no
Postgres. CI starts a Postgres service, so nothing is skipped there.
"""

from __future__ import annotations

import pytest


def _reachable() -> bool:
    try:
        from src.api import store_queries
        from src.db.schema import ensure_schema

        store_queries.ping(timeout=2.0)
        ensure_schema()
        return True
    except Exception:
        return False


POSTGRES_AVAILABLE = _reachable()

requires_postgres = pytest.mark.skipif(
    not POSTGRES_AVAILABLE, reason="Postgres not reachable"
)
