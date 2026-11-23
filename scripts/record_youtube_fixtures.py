"""Record the YouTube replay fixtures from public RSS feeds.

    python scripts/record_youtube_fixtures.py

Reads the channels in fixtures/brightdata/channels.json, fetches each one's
public feed (https://www.youtube.com/feeds/videos.xml, no API key needed) and
writes fixtures/youtube/channels.json and videos.json in the shape the YouTube
Data API returns. A feed carries the latest 15 uploads with their title,
description, publish time, views and likes. It carries no duration and no
comment count, so recorded videos have neither.
"""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "fixtures" / "brightdata" / "channels.json"
OUT = ROOT / "fixtures" / "youtube"
FEED = "https://www.youtube.com/feeds/videos.xml"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


def channel_resource(row: dict) -> dict:
    return {
        "kind": "youtube#channel",
        "id": row["id"],
        "snippet": {
            "title": row.get("name", ""),
            "description": row.get("Description", ""),
            "publishedAt": row.get("created_date", ""),
            "country": "",
            "thumbnails": {"default": {"url": row.get("profile_image", "")}},
        },
        "statistics": {
            "subscriberCount": str(row.get("subscribers") or 0),
            "viewCount": str(row.get("views") or 0),
            "videoCount": str(row.get("videos_count") or 0),
        },
        "contentDetails": {"relatedPlaylists": {"uploads": "UU" + row["id"][2:]}},
    }


def video_resources(feed_xml: str) -> list[dict]:
    root = ET.fromstring(feed_xml)
    videos = []
    for entry in root.findall("atom:entry", NS):
        video_id = entry.findtext("yt:videoId", namespaces=NS)
        link = entry.find("atom:link", NS).get("href", "")
        group = entry.find("media:group", NS)
        stats = group.find("media:community/media:statistics", NS)
        rating = group.find("media:community/media:starRating", NS)
        thumb = group.find("media:thumbnail", NS)
        videos.append({
            "kind": "youtube#video",
            "id": video_id,
            "isShort": "/shorts/" in link,
            "snippet": {
                "channelId": entry.findtext("yt:channelId", namespaces=NS),
                "title": entry.findtext("atom:title", namespaces=NS),
                "description": group.findtext("media:description", default="", namespaces=NS),
                "publishedAt": entry.findtext("atom:published", namespaces=NS),
                "thumbnails": {"high": {"url": thumb.get("url") if thumb is not None else ""}},
            },
            "statistics": {
                "viewCount": stats.get("views", "0") if stats is not None else "0",
                "likeCount": rating.get("count", "0") if rating is not None else "0",
            },
            "contentDetails": {},
        })
    return videos


def main() -> None:
    rows = [r for r in json.loads(SOURCE.read_text()) if r.get("id", "").startswith("UC")]
    channels, videos = [], []
    with httpx.Client(timeout=20, headers={"User-Agent": "graph-research fixture recorder"}) as client:
        for row in rows:
            response = client.get(FEED, params={"channel_id": row["id"]})
            if response.status_code != 200:
                print(f"skip {row['id']}: HTTP {response.status_code}")
                continue
            channels.append(channel_resource(row))
            recorded = video_resources(response.text)
            videos.extend(recorded)
            print(f"{row.get('name', row['id'])}: {len(recorded)} videos")
            time.sleep(0.5)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "channels.json").write_text(json.dumps(channels, indent=1, ensure_ascii=False) + "\n")
    (OUT / "videos.json").write_text(json.dumps(videos, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(channels)} channels, {len(videos)} videos -> {OUT}")


if __name__ == "__main__":
    main()
