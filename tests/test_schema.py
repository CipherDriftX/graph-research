"""schema.sql applied to an empty Postgres namespace.

Each test gets its own namespace, so the checks run against a truly fresh
database shape without touching the tables the rest of the suite uses.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from src.config import get_config
from src.db.schema import TABLES, create_schema, drop_schema
from tests.pg import requires_postgres

pytestmark = requires_postgres


@pytest.fixture
def conn():
    namespace = f"schema_test_{uuid.uuid4().hex[:8]}"
    connection = psycopg.connect(get_config().postgres.connection_string)
    with connection.cursor() as cur:
        cur.execute(f"CREATE SCHEMA {namespace}")
        cur.execute(f"SET search_path TO {namespace}")
    connection.commit()
    connection.namespace = namespace
    yield connection
    connection.rollback()
    with connection.cursor() as cur:
        cur.execute(f"DROP SCHEMA {namespace} CASCADE")
    connection.commit()
    connection.close()


def _tables(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            (conn.namespace,),
        )
        return {row[0] for row in cur.fetchall()}


def _columns(conn, table: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s",
            (conn.namespace, table),
        )
        return {row[0] for row in cur.fetchall()}


def test_one_apply_creates_every_table(conn):
    create_schema(conn)
    assert _tables(conn) == set(TABLES)


def test_one_apply_gives_crime_metadata_its_footage_columns(conn):
    create_schema(conn)
    assert {
        "interrogation_available",
        "bodycam_available",
        "cctv_available",
        "call_911_available",
        "court_footage_available",
    } <= _columns(conn, "crime_case_metadata")


def test_applying_twice_changes_nothing(conn):
    create_schema(conn)
    before = {t: _columns(conn, t) for t in TABLES}
    create_schema(conn)
    assert {t: _columns(conn, t) for t in TABLES} == before


def test_a_video_needs_an_existing_channel(conn):
    create_schema(conn)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO videos (video_id, channel_id, title) VALUES ('v1', 'UC_missing', 't')"
            )


def test_deleting_a_channel_removes_its_videos(conn):
    create_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO channels (channel_id, title, discovery_method) VALUES ('UC1', 'c', 'keyword')"
        )
        cur.execute("INSERT INTO videos (video_id, channel_id, title) VALUES ('v1', 'UC1', 't')")
        cur.execute("DELETE FROM channels WHERE channel_id = 'UC1'")
        cur.execute("SELECT count(*) FROM videos")
        assert cur.fetchone()[0] == 0


def test_drop_schema_removes_every_table(conn):
    create_schema(conn)
    drop_schema(conn)
    assert _tables(conn) == set()
