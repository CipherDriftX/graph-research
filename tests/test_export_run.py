"""export_run writes a run's files from the store."""

from __future__ import annotations

import json

import pytest

from src import export
from src.db.connection import get_connection, put_connection
from tests.pg import requires_postgres

pytestmark = requires_postgres

RUN = "run-test-export"
CHANNEL = "UC_export_test"
VIDEO = "vid_export_test"


@pytest.fixture
def tagged_run(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "export_dir", lambda run_id: tmp_path)
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO channels (channel_id, title, subscriber_count, discovery_method) "
            "VALUES (%s, 'Export test', 120000, 'keyword') ON CONFLICT (channel_id) DO NOTHING",
            (CHANNEL,),
        )
        cur.execute(
            "INSERT INTO videos (video_id, channel_id, title, view_count) "
            "VALUES (%s, %s, 'A video', 5000) ON CONFLICT (video_id) DO NOTHING",
            (VIDEO, CHANNEL),
        )
        for entity_type, entity_id in (("channel", CHANNEL), ("video", VIDEO)):
            cur.execute(
                "INSERT INTO category_tags (entity_type, entity_id, tree_node_id, run_id) "
                "VALUES (%s, %s, 'root', %s) ON CONFLICT DO NOTHING",
                (entity_type, entity_id, RUN),
            )
    conn.commit()
    yield tmp_path
    with conn.cursor() as cur:
        cur.execute("DELETE FROM category_tags WHERE run_id = %s", (RUN,))
        cur.execute("DELETE FROM channels WHERE channel_id = %s", (CHANNEL,))
    conn.commit()
    put_connection(conn)


def test_the_bundle_holds_the_runs_channels_and_videos(tagged_run):
    out = export.export_run(RUN)
    bundle = json.loads((out / "research_bundle.json").read_text())
    assert [c["channel_id"] for c in bundle["channels"]] == [CHANNEL]
    assert [v["video_id"] for v in bundle["videos"]] == [VIDEO]
    assert json.loads((out / "manifest.json").read_text())["run_id"] == RUN
