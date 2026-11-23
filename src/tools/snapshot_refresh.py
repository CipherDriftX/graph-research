"""Refresh the stats of every stored channel and video from the YouTube API.

No discovery and no LLM calls. Each run writes one snapshot row per channel
and per video, which is what growth measures are computed from. Cost is one
quota unit per 50 channels plus one per 50 videos.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from src.tools.dedup import persist_channel_snapshot
from src.tools.youtube_api import YouTubeAPIClient

logger = structlog.get_logger(__name__)


def _ids(conn, sql: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(sql)
        return [row[0] for row in cur.fetchall()]


def _age_hours(published_at: str) -> float | None:
    if not published_at:
        return None
    published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    return round((datetime.now(timezone.utc) - published).total_seconds() / 3600.0, 2)


def refresh_snapshots(conn, run_id: str, client: YouTubeAPIClient | None = None) -> dict:
    """Fetch current stats for the whole store and record them under run_id."""
    client = client or YouTubeAPIClient()

    channel_ids = _ids(conn, "SELECT channel_id FROM channels ORDER BY channel_id")
    channels = client.get_channels(channel_ids)
    for ch in channels:
        persist_channel_snapshot(
            conn, ch["channel_id"], run_id,
            ch.get("subscriber_count", 0), ch.get("view_count", 0), ch.get("video_count", 0),
        )
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE channels SET subscriber_count = %s, updated_at = NOW() WHERE channel_id = %s",
                (ch.get("subscriber_count", 0), ch["channel_id"]),
            )
        conn.commit()

    video_ids = _ids(conn, "SELECT video_id FROM videos ORDER BY video_id")
    videos = client.get_videos(video_ids)
    with conn.cursor() as cur:
        for v in videos:
            cur.execute(
                "INSERT INTO video_snapshots "
                "(video_id, run_id, view_count, like_count, comment_count, video_age_hours) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (video_id, run_id) DO NOTHING",
                (v["video_id"], run_id, v.get("view_count", 0), v.get("like_count", 0),
                 v.get("comment_count", 0), _age_hours(v.get("published_at", ""))),
            )
            cur.execute(
                "UPDATE videos SET view_count = %s, like_count = %s, comment_count = %s "
                "WHERE video_id = %s",
                (v.get("view_count", 0), v.get("like_count", 0), v.get("comment_count", 0),
                 v["video_id"]),
            )
    conn.commit()

    summary = {
        "channels_requested": len(channel_ids),
        "channels_refreshed": len(channels),
        "videos_requested": len(video_ids),
        "videos_refreshed": len(videos),
        "quota_used": client.get_quota_used(),
    }
    logger.info("snapshot_refresh_done", run_id=run_id, **summary)
    return summary
