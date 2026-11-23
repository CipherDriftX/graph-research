"""The MCP server registers its tools against the installed mcp SDK."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("mcp")

from src.mcp_server import build_server  # noqa: E402


def test_the_server_exposes_three_tools():
    tools = asyncio.run(build_server().list_tools())
    assert {t.name for t in tools} == {"research_niches", "search_channels", "top_outlier_videos"}


def test_search_channels_passes_the_query_through(monkeypatch):
    seen = {}

    def fake_search(query, limit):
        seen.update(query=query, limit=limit)
        return [{"channel_id": "UC1", "title": "Ben Felix"}]

    monkeypatch.setattr("src.api.store_queries.search_channels", fake_search)
    result = asyncio.run(build_server().call_tool("search_channels", {"query": "ben", "limit": 500}))
    assert seen == {"query": "ben", "limit": 200}
    assert result.structured_content == {"result": [{"channel_id": "UC1", "title": "Ben Felix"}]}
