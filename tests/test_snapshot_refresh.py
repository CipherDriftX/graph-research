"""--snapshot fetches fresh stats from YouTube and records them per run."""

from __future__ import annotations

import pytest

from src.db.connection import get_connection, put_connection
from src.tools.snapshot_refresh import refresh_snapshots
from tests.pg import requires_postgres

pytestmark = requires_postgres

CHANNEL = "UC_snapshot_test"
VIDEO = "vid_snapshot_test"
RUN = "run-test-snapshot"


class FakeYouTube:
    def __init__(self):
        self.quota = 0

    def get_channels(self, ids):
        self.quota += 1
        return [
            {"channel_id": i, "subscriber_count": 2000, "view_count": 90000, "video_count": 12}
            for i in ids if i == CHANNEL
        ]

    def get_videos(self, ids):
        self.quota += 1
        return [
            {"video_id": i, "view_count": 5000, "like_count": 300, "comment_count": 40,
             "published_at": "2026-01-01T00:00:00Z"}
            for i in ids if i == VIDEO
        ]

    def get_quota_used(self):
        return self.quota


@pytest.fixture
def conn():
    c = get_connection()
    with c.cursor() as cur:
        cur.execute(
            "INSERT INTO channels (channel_id, title, subscriber_count, discovery_method) "
            "VALUES (%s, 'Snapshot test', 1000, 'keyword') ON CONFLICT (channel_id) DO NOTHING",
            (CHANNEL,),
        )
        cur.execute(
            "INSERT INTO videos (video_id, channel_id, title, view_count) "
            "VALUES (%s, %s, 'v', 100) ON CONFLICT (video_id) DO NOTHING",
            (VIDEO, CHANNEL),
        )
    c.commit()
    yield c
    with c.cursor() as cur:
        cur.execute("DELETE FROM video_snapshots WHERE run_id = %s", (RUN,))
        cur.execute("DELETE FROM channel_snapshots WHERE run_id = %s", (RUN,))
        cur.execute("DELETE FROM channels WHERE channel_id = %s", (CHANNEL,))
    c.commit()
    put_connection(c)


def _one(conn, sql, params):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def test_the_snapshot_holds_the_numbers_youtube_returned(conn):
    refresh_snapshots(conn, RUN, client=FakeYouTube())
    assert _one(conn, "SELECT subscriber_count, total_view_count FROM channel_snapshots "
                      "WHERE channel_id = %s AND run_id = %s", (CHANNEL, RUN)) == (2000, 90000)
    assert _one(conn, "SELECT view_count, like_count FROM video_snapshots "
                      "WHERE video_id = %s AND run_id = %s", (VIDEO, RUN)) == (5000, 300)


def test_the_stored_rows_move_to_the_new_numbers(conn):
    refresh_snapshots(conn, RUN, client=FakeYouTube())
    assert _one(conn, "SELECT subscriber_count FROM channels WHERE channel_id = %s", (CHANNEL,)) == (2000,)
    assert _one(conn, "SELECT view_count FROM videos WHERE video_id = %s", (VIDEO,)) == (5000,)


def test_the_summary_counts_what_came_back(conn):
    summary = refresh_snapshots(conn, RUN, client=FakeYouTube())
    assert summary["channels_refreshed"] == 1
    assert summary["videos_refreshed"] == 1
    assert summary["channels_requested"] >= 1
    assert summary["quota_used"] == 2
