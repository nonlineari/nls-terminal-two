"""Apple Marketing Tools most-played songs, one public storefront per market."""

from __future__ import annotations

import json
import logging
import time

from src.config import MARKETS, iso_now
from src.ingestion.failures import record_failure
from src.ingestion.http_util import fetch

logger = logging.getLogger(__name__)

CHART_LIMIT = 25


def fetch_apple_charts(run_id: str) -> dict:
    charts: dict[str, dict] = {}
    for market in MARKETS:
        url = (
            "https://rss.applemarketingtools.com/api/v2/"
            f"{market.apple_store}/music/most-played/{CHART_LIMIT}/songs.json"
        )
        logger.info("Apple chart %s", market.code)
        result = fetch(url, timeout=40, max_attempts=3)
        if not result.ok or result.body is None:
            record_failure(
                run_id,
                source="apple_rss",
                market=market.code,
                url=url,
                reason=result.error,
                theme="streaming_chart_snapshot",
            )
            charts[market.code] = {"ok": False, "url": url, "error": result.error, "body": None}
        else:
            try:
                body = json.loads(result.body.decode("utf-8"))
            except json.JSONDecodeError as exc:
                record_failure(
                    run_id,
                    source="apple_rss",
                    market=market.code,
                    url=result.url,
                    reason=f"invalid JSON: {exc}",
                    theme="streaming_chart_snapshot",
                )
                charts[market.code] = {"ok": False, "url": result.url, "error": str(exc), "body": None}
            else:
                count = len((body.get("feed") or {}).get("results") or [])
                logger.info("Apple chart %s returned %s tracks", market.code, count)
                charts[market.code] = {
                    "ok": True,
                    "url": result.url,
                    "status": result.status,
                    "track_count": count,
                    "body": body,
                }
        time.sleep(0.25)
    ok_count = sum(1 for chart in charts.values() if chart.get("ok"))
    return {
        "source": "apple_rss",
        "pulled_at": iso_now(),
        "run_id": run_id,
        "chart_limit": CHART_LIMIT,
        "docs": "https://developer.apple.com/documentation/applemusicrss",
        "ok": ok_count > 0,
        "markets_ok": ok_count,
        "charts": charts,
    }
