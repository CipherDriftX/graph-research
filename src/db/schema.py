"""Create the store schema and seed its reference tables.

The schema lives in schema.sql as one ordered, idempotent script, so a fresh
database and an existing one end up identical after a single apply.
"""

from __future__ import annotations

from pathlib import Path

SCHEMA_SQL = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")

#: Tables in dependency order, children first, for drop_schema.
TABLES = (
    "video_reveal_mechanisms",
    "crime_case_metadata",
    "channel_failure_factors",
    "channel_success_factors",
    "failure_factor_taxonomy",
    "success_factor_taxonomy",
    "channel_cohorts",
    "cohort_definitions",
    "run_niche_cluster",
    "niche_adjacency",
    "run_niche_families",
    "channel_niches",
    "niche_taxonomy",
    "primary_niche_groups",
    "video_snapshots",
    "channel_snapshots",
    "harness_runs",
    "discovery_edges",
    "category_tags",
    "videos",
    "channels",
)


def create_schema(conn) -> None:
    """Apply schema.sql in one transaction."""
    cur = conn.cursor()
    try:
        cur.execute(SCHEMA_SQL)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def ensure_schema() -> None:
    """Create the schema if needed and seed the reference tables."""
    from src.db.connection import get_connection, put_connection
    from src.db.seeds import seed_taxonomies

    conn = get_connection()
    try:
        create_schema(conn)
        seed_taxonomies(conn)
    finally:
        put_connection(conn)


def drop_schema(conn) -> None:
    """Drop every table this module creates."""
    cur = conn.cursor()
    try:
        for table in TABLES:
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
