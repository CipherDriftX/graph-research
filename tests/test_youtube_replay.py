"""YouTube replay mode answers from the recorded public fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import config
from src.tools.youtube_api import YouTubeAPIClient

FIXTURES = Path("fixtures/youtube")
BEN_FELIX = "UCDXTQ8nWmx_EhZ2v-kp7QxA"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("YOUTUBE_MODE", "replay")
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setattr(config, "_config", None)
    yield YouTubeAPIClient()


def test_channels_come_back_with_their_recorded_counts(client):
    [channel] = client.get_channels([BEN_FELIX, "UC_not_recorded"])
    assert channel["title"] == "Ben Felix"
    assert channel["subscriber_count"] == 624000


def test_a_channel_scan_returns_only_its_own_videos(client):
    videos = client.get_channel_videos(BEN_FELIX, max_results=50)
    assert videos
    assert {v["channel_id"] for v in videos} == {BEN_FELIX}


def test_a_missing_duration_reads_as_unknown_not_zero(client):
    videos = client.get_channel_videos(BEN_FELIX, max_results=5)
    assert all(v["duration_seconds"] is None for v in videos)


def test_the_upload_breakdown_adds_up(client):
    breakdown = client.get_channel_upload_breakdown(BEN_FELIX)
    assert breakdown["long"] + breakdown["shorts"] + breakdown["live"] == breakdown["total"]


def test_shorts_and_long_form_come_from_separate_playlists(client):
    recorded = json.loads((FIXTURES / "videos.json").read_text())
    channel = next(v["snippet"]["channelId"] for v in recorded if v["isShort"])
    shorts = {v["id"] for v in recorded if v["isShort"] and v["snippet"]["channelId"] == channel}
    assert client.get_channel_shorts_ids(channel) == shorts
