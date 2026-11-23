"""The run's niche queue.

A run researches one niche at a time. queue_niches sets the first niche the
user named as the target; expand_niche_adjacency then fills the rest of the
queue. Two later exits need the same "are there more niches" check, so it
lives here once.
"""

from __future__ import annotations

import time

from src.state import NodeLog


def queue_niches(state: dict) -> dict:
    """Make the first requested niche the target of the run."""
    start = time.monotonic()
    niches = [n.strip() for n in state.get("candidate_niches", []) if n and n.strip()]
    target = niches[0] if niches else ""
    return {
        "selected_niche": target,
        "next_action": "niche_queued" if target else "no_niches",
        "node_logs": [
            NodeLog(
                node_name="queue_niches",
                thread_id=state.get("thread_id", ""),
                input_summary={"requested": niches, "target": target},
                latency_ms=(time.monotonic() - start) * 1000,
            ).model_dump()
        ],
    }


def has_more_niches(state: dict) -> bool:
    niches = state.get("selected_niches") or []
    return state.get("niche_index", 0) + 1 < len(niches)


def advance_to_next_niche(state: dict) -> dict:
    next_index = state.get("niche_index", 0) + 1
    niches = state.get("selected_niches") or []
    next_niche = niches[next_index] if next_index < len(niches) else ""
    return {
        "niche_index": next_index,
        "selected_niche": next_niche,
        "tree": {},
        "active_node_id": None,
    }
