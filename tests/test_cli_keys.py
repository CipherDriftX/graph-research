"""The CLI names the missing keys before it starts a run."""

from __future__ import annotations

import pytest

from src import config
from src.cli import missing_keys


@pytest.fixture
def env(monkeypatch):
    for name in ("YOUTUBE_API_KEY", "OPENROUTER_API_KEY", "BRIGHTDATA_API_KEY",
                 "YOUTUBE_MODE", "BRIGHTDATA_MODE"):
        monkeypatch.delenv(name, raising=False)

    def set_env(**values):
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        monkeypatch.setattr(config, "_config", None)

    set_env()
    return set_env


def test_a_research_run_needs_all_three_keys(env):
    assert missing_keys("research") == ["YOUTUBE_API_KEY", "OPENROUTER_API_KEY", "BRIGHTDATA_API_KEY"]


def test_a_snapshot_needs_only_youtube(env):
    assert missing_keys("snapshot_refresh") == ["YOUTUBE_API_KEY"]


def test_replayed_services_need_no_key(env):
    env(YOUTUBE_MODE="replay", BRIGHTDATA_MODE="replay", OPENROUTER_API_KEY="sk-test")
    assert missing_keys("research") == []
