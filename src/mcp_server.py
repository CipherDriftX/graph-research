"""MCP server: run research and read the store from an MCP client.

    python -m src.mcp_server

Speaks MCP over stdio. Needs the `mcp` extra: pip install -e '.[mcp]'.
"""

from __future__ import annotations

import sys
from typing import Any


async def research_niches(niches: list[str]) -> dict[str, Any]:
    """Research the given niches and export the workbook.

    The first niche is the target. The run uses the profile and keys from
    the environment, exactly like the CLI.
    """
    from src.cli import _run
    from src.export import export_dir

    final = await _run(niches, resume_thread_id=None)
    run_id = final.get("run_id", "")
    return {
        "run_id": run_id,
        "niches": final.get("selected_niches") or [final.get("selected_niche", "")],
        "channels_enriched": final.get("channels_enriched_this_run", 0),
        "budget_spent_usd": round(float(final.get("budget_spent_usd", 0.0)), 4),
        "export_dir": str(export_dir(run_id)) if run_id else "",
        "errors": [e.get("message", "") for e in final.get("errors", [])[:10]],
    }


def search_channels(query: str = "", limit: int = 25) -> list[dict[str, Any]]:
    """Channels in the store whose title or id contains `query`, largest first."""
    from src.api import store_queries

    return store_queries.search_channels(query, limit=max(1, min(limit, 200)))


def top_outlier_videos(limit: int = 25) -> list[dict[str, Any]]:
    """Videos that most outperform their own channel's typical views."""
    from src.api import store_queries

    return store_queries.top_outlier_videos(limit=max(1, min(limit, 200)))


def build_server():
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("graph-research")
    server.tool()(research_niches)
    server.tool()(search_channels)
    server.tool()(top_outlier_videos)
    return server


def main() -> None:
    try:
        server = build_server()
    except ImportError:
        sys.exit("The MCP server needs the mcp extra: pip install -e '.[mcp]'")
    server.run()


if __name__ == "__main__":
    main()
