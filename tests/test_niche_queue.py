"""Order of the niche queue: target, then requested niches, then adjacent ones."""

from __future__ import annotations

import asyncio

from src.nodes import expand_niche_adjacency as mod


def _state(*niches: str) -> dict:
    return {
        "candidate_niches": list(niches),
        "selected_niche": niches[0] if niches else "",
        "run_id": "run-q",
        "thread_id": "t-q",
    }


def test_requested_niches_follow_the_target_when_the_store_is_down(monkeypatch):
    def down():
        raise ConnectionError("no store")

    monkeypatch.setattr(mod, "get_connection", down)
    result = asyncio.run(mod.expand_niche_adjacency(_state("finance", "crime", "finance")))
    assert result["selected_niches"] == ["finance", "crime"]


def test_an_empty_request_queues_nothing():
    result = asyncio.run(mod.expand_niche_adjacency(_state()))
    assert result["selected_niches"] == []
