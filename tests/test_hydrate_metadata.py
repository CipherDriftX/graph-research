"""hydrate_metadata against a real Postgres, with the YouTube client faked.

The node's job is to turn discovered channel ids into stored channel and
video rows tagged with the run. These tests run the real persistence loop,
so a broken write path fails here instead of in a live run.
"""

from __future__ import annotations

import sys

import pytest

import src.tools.hydrate_metadata  # noqa: F401
from tests.pg import requires_postgres

mod = sys.modules["src.tools.hydrate_metadata"]

pytestmark = requires_postgres

RUN = "run-test-hydrate"
OWN, OTHER, BROKEN = "UC_test_hyd_own", "UC_test_hyd_other", "UC_test_hyd_broken"


def _video(video_id: str, channel_id: str) -> dict:
    return {
        "video_id": video_id,
        "channel_id": channel_id,
        "title": f"Video {video_id}",
        "view_count": 1000,
        "like_count": 10,
        "comment_count": 1,
        "published_at": "2026-01-01T00:00:00Z",
        "duration_seconds": 600,
    }


class FakeYouTube:
    """Answers the calls hydrate_metadata makes, from in-memory data."""

    channels: dict[str, dict] = {}
    videos: dict[str, list[dict]] = {}

    def __init__(self) -> None:
        self._quota = 0

    def seed_quota_used(self, units: int) -> None:
        self._quota = max(self._quota, int(units or 0))

    def quota_consumed_this_call(self, baseline: int) -> int:
        return max(0, self._quota - int(baseline or 0))

    def get_quota_used(self) -> int:
        return self._quota

    def get_channels(self, ids: list[str]) -> list[dict]:
        self._quota += 1
        return [dict(self.channels[i]) for i in ids if i in self.channels]

    def get_channel_videos(self, channel_id: str, max_results: int = 50, deep_scan: bool = True):
        self._quota += 1
        return [dict(v) for v in self.videos.get(channel_id, [])]

    def get_channel_upload_breakdown(self, channel_id: str) -> dict:
        return {"long": len(self.videos.get(channel_id, [])), "shorts": 0, "live": 0}

    def get_channel_shorts_ids(self, channel_id: str, published_after=None) -> set[str]:
        return set()


def _channel(cid: str, subs: int = 120_000) -> dict:
    return {
        "channel_id": cid,
        "title": f"Channel {cid}",
        "description": "",
        "subscriber_count": subs,
        "view_count": 5_000_000,
        "video_count": 40,
        "published_at": "2020-01-01T00:00:00Z",
    }


def _cleanup(conn) -> None:
    cur = conn.cursor()
    ids = [OWN, OTHER, BROKEN]
    cur.execute("DELETE FROM category_tags WHERE run_id = %s", (RUN,))
    cur.execute("DELETE FROM channel_snapshots WHERE run_id = %s", (RUN,))
    cur.execute("DELETE FROM videos WHERE channel_id = ANY(%s)", (ids,))
    cur.execute("DELETE FROM channels WHERE channel_id = ANY(%s)", (ids,))
    conn.commit()
    cur.close()


@pytest.fixture
def conn(monkeypatch):
    from src.db.connection import get_connection, put_connection

    monkeypatch.setattr(mod, "YouTubeAPIClient", FakeYouTube)
    connection = get_connection()
    _cleanup(connection)
    yield connection
    _cleanup(connection)
    put_connection(connection)


def _state(*ids: str) -> dict:
    return {
        "discovered_channel_ids": list(ids),
        "run_id": RUN,
        "thread_id": "t-hyd",
        "active_node_id": "root",
    }


def _rows(conn, sql: str, params: tuple) -> list[tuple]:
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def test_a_foreign_owned_video_is_dropped_and_the_channel_is_kept(conn):
    FakeYouTube.channels = {OWN: _channel(OWN)}
    FakeYouTube.videos = {OWN: [_video("vid_test_own", OWN), _video("vid_test_stray", OTHER)]}

    result = mod.hydrate_metadata(_state(OWN))

    summary = result["node_logs"][0]["input_summary"]
    assert result.get("errors", []) == []
    assert summary["channels_hydrated"] == 1
    assert summary["foreign_owned_videos_dropped"] == 1
    stored = _rows(conn, "SELECT video_id FROM videos WHERE channel_id = ANY(%s)", ([OWN, OTHER],))
    assert stored == [("vid_test_own",)]


def test_one_failing_channel_does_not_take_the_others_with_it(conn, monkeypatch):
    FakeYouTube.channels = {cid: _channel(cid) for cid in (OWN, BROKEN, OTHER)}
    FakeYouTube.videos = {cid: [_video(f"vid_test_{cid[-5:]}", cid)] for cid in (OWN, BROKEN, OTHER)}

    real_persist = mod.persist_channel

    def persist(conn_, ch):
        if ch["channel_id"] == BROKEN:
            raise RuntimeError("simulated write failure")
        return real_persist(conn_, ch)

    monkeypatch.setattr(mod, "persist_channel", persist)
    result = mod.hydrate_metadata(_state(OWN, BROKEN, OTHER))

    summary = result["node_logs"][0]["input_summary"]
    assert summary["channels_attempted"] == 3
    assert summary["channels_hydrated"] == 2
    assert len(result["errors"]) == 1
    tagged = _rows(
        conn,
        "SELECT entity_id FROM category_tags WHERE run_id = %s AND entity_type = 'channel' "
        "ORDER BY entity_id",
        (RUN,),
    )
    assert tagged == [(OTHER,), (OWN,)]
