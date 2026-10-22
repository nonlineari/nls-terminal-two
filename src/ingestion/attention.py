"""Wikidata sitelinks plus Wikimedia pageviews for platform attention.

Hong Kong uses Cantonese Wikipedia (zh-yue), not the same zh.wikipedia edition
as mainland China, so the two markets are not the same pageview series.
A language edition is still not a country panel: readers abroad count, and
articles that do not exist on that wiki are gaps, not zeros we filled in.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date
from urllib.parse import quote

from src.config import MARKETS, iso_now
from src.ingestion.failures import record_failure
from src.ingestion.http_util import fetch

logger = logging.getLogger(__name__)

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
PAGEVIEW_API = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"

# (qid, key, channel, tokens that must all appear in the English label or description)
PINNED: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("Q689141", "spotify", "streaming_dsp", ("spotify", "streaming")),
    ("Q20056642", "apple_music", "streaming_dsp", ("apple", "music")),
    ("Q28404534", "youtube_music", "streaming_dsp", ("youtube", "music")),
    ("Q4740860", "amazon_music", "streaming_dsp", ("amazon", "music")),
    ("Q12595115", "melon", "streaming_dsp", ("korean", "music")),
    ("Q20856958", "line_music", "streaming_dsp", ("line", "music")),
    ("Q28187024", "joox", "streaming_dsp", ("joox", "music")),
    ("Q10852229", "qq_music", "streaming_dsp", ("qq", "music")),
    ("Q20063955", "netease_cloud_music", "streaming_dsp", ("netease", "music")),
    ("Q10851252", "kkbox", "streaming_dsp", ("kkbox", "music")),
    ("Q48938223", "tiktok", "short_video", ("tiktok", "video")),
    ("Q866", "youtube", "short_video", ("youtube", "video")),
    ("Q209330", "instagram", "social_influencer", ("instagram",)),
)

SEARCHES: tuple[dict, ...] = (
    {
        "queries": ("AWA music streaming", "AWA streaming service"),
        "key": "awa",
        "channel": "streaming_dsp",
        "must": ("music", "stream"),
        "must_not": ("language", "village", "given name", "award", "sport"),
    },
    {
        "queries": ("Genie music streaming service",),
        "key": "genie_music",
        "channel": "streaming_dsp",
        "must": ("music", "stream"),
        "must_not": ("award", "band", "singer", "company"),
    },
    {
        "queries": ("Bugs! music streaming", "Bugs music Korea"),
        "key": "bugs",
        "channel": "streaming_dsp",
        "must": ("music", "korea"),
        "must_not": ("award", "insect"),
    },
)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _last_complete_month(today: date) -> tuple[int, int]:
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


def pageview_window(today: date | None = None) -> dict:
    """24 months ending at the last complete UTC month: prior 12 and last 12."""
    today = today or date.today()
    end_year, end_month = _last_complete_month(today)
    last_year, last_month = _shift_month(end_year, end_month, -11)
    prior_year, prior_month = _shift_month(end_year, end_month, -23)
    return {
        "prior_start_ym": prior_year * 100 + prior_month,
        "last_start_ym": last_year * 100 + last_month,
        "end_ym": end_year * 100 + end_month,
        "request_start": f"{prior_year}{prior_month:02d}0100",
        "request_end": f"{end_year}{end_month:02d}0100",
    }


def _entity_text(entity: dict) -> str:
    labels = entity.get("labels") or {}
    # Some items keep the Latin name on the multilingual label (`mul`) and
    # have no `en` label. Instagram is one of those.
    label = ""
    for language in ("en", "mul"):
        value = (labels.get(language) or {}).get("value")
        if isinstance(value, str) and value.strip():
            label = value
            break
    descriptions = entity.get("descriptions") or {}
    description = (descriptions.get("en") or descriptions.get("mul") or {}).get("value") or ""
    return f"{label} {description}".strip().lower()


def _search_qid(query: str, must: tuple[str, ...], must_not: tuple[str, ...]) -> tuple[str | None, str]:
    result = fetch(
        WIKIDATA_API,
        params={
            "action": "wbsearchentities",
            "search": query,
            "language": "en",
            "format": "json",
            "type": "item",
            "limit": 8,
        },
        timeout=40,
        max_attempts=3,
    )
    if not result.ok or result.body is None:
        return None, result.error or "search failed"
    try:
        payload = json.loads(result.body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    matched: list[str] = []
    for hit in payload.get("search") or []:
        text = f"{hit.get('label') or ''} {hit.get('description') or ''}".lower()
        if any(token in text for token in must_not):
            continue
        if all(token in text for token in must):
            matched.append(hit["id"])
    if len(matched) == 1:
        return matched[0], "ok"
    if len(matched) > 1:
        return None, f"ambiguous: {matched}"
    return None, "no match"


def _fetch_entities(qids: list[str]) -> dict:
    if not qids:
        return {}
    result = fetch(
        WIKIDATA_API,
        params={
            "action": "wbgetentities",
            "ids": "|".join(qids),
            "props": "labels|descriptions|sitelinks",
            "languages": "en|mul",
            "format": "json",
        },
        timeout=60,
        max_attempts=3,
    )
    if not result.ok or result.body is None:
        raise RuntimeError(result.error or "wbgetentities failed")
    payload = json.loads(result.body.decode("utf-8"))
    return payload.get("entities") or {}


def _titles(entity: dict) -> dict[str, str | None]:
    sitelinks = entity.get("sitelinks") or {}
    titles: dict[str, str | None] = {}
    for market in MARKETS:
        link = sitelinks.get(market.wiki_site) or {}
        title = link.get("title")
        titles[market.code] = title if isinstance(title, str) and title else None
    return titles


def resolve_entities(run_id: str) -> list[dict]:
    specs: list[tuple[str, str, str, tuple[str, ...]]] = list(PINNED)
    for search in SEARCHES:
        found = None
        detail = "no match"
        for query in search["queries"]:
            found, detail = _search_qid(query, search["must"], search["must_not"])
            time.sleep(0.2)
            if found:
                break
        if not found:
            record_failure(
                run_id,
                source="wikidata_search",
                entity=search["key"],
                reason=detail,
                theme="platform_attention",
                note="Optional local platform. No pageviews were invented for it.",
            )
            continue
        specs.append((found, search["key"], search["channel"], search["must"]))

    try:
        entities = _fetch_entities([spec[0] for spec in specs])
    except RuntimeError as exc:
        record_failure(
            run_id,
            source="wikidata",
            url=WIKIDATA_API,
            reason=str(exc),
            theme="platform_attention",
        )
        return []

    resolved: list[dict] = []
    for qid, key, channel, tokens in specs:
        entity = entities.get(qid) or {}
        if entity.get("missing") is not None and "labels" not in entity:
            record_failure(
                run_id,
                source="wikidata",
                entity=key,
                qid=qid,
                reason="entity missing",
                theme="platform_attention",
            )
            continue
        text = _entity_text(entity)
        if not all(token in text for token in tokens):
            record_failure(
                run_id,
                source="wikidata",
                entity=key,
                qid=qid,
                reason=f"description did not match {tokens}: {text!r}",
                theme="platform_attention",
                note="Rejected so a same-name article (for example a fruit or an award) cannot enter the features.",
            )
            resolved.append(
                {
                    "qid": qid,
                    "key": key,
                    "channel": channel,
                    "accepted": False,
                    "description": text,
                    "titles": {},
                }
            )
            continue
        resolved.append(
            {
                "qid": qid,
                "key": key,
                "channel": channel,
                "accepted": True,
                "description": text,
                "titles": _titles(entity),
            }
        )
    return resolved


def _pageview_url(project: str, title: str, window: dict) -> str:
    title_path = quote(title.replace(" ", "_"), safe="")
    return (
        f"{PAGEVIEW_API}/{project}/all-access/user/{title_path}/monthly/"
        f"{window['request_start']}/{window['request_end']}"
    )


def fetch_attention(run_id: str, today: date | None = None) -> dict:
    window = pageview_window(today)
    logger.info(
        "Pageview window %s to %s",
        window["request_start"],
        window["request_end"],
    )
    entities = resolve_entities(run_id)
    series: list[dict] = []
    accepted = [entity for entity in entities if entity.get("accepted")]
    if not accepted:
        record_failure(
            run_id,
            source="wikimedia_pageviews",
            reason="no accepted platform entities",
            theme="platform_attention",
        )
    for entity in accepted:
        for market in MARKETS:
            title = (entity.get("titles") or {}).get(market.code)
            if not title:
                series.append(
                    {
                        "market": market.code,
                        "entity": entity["key"],
                        "qid": entity["qid"],
                        "channel": entity["channel"],
                        "project": market.wiki_project,
                        "title": None,
                        "ok": False,
                        "reason": "no_sitelink",
                        "items": [],
                    }
                )
                continue
            url = _pageview_url(market.wiki_project, title, window)
            result = fetch(url, timeout=40, max_attempts=4)
            time.sleep(0.5)
            if not result.ok or result.body is None:
                record_failure(
                    run_id,
                    source="wikimedia_pageviews",
                    market=market.code,
                    entity=entity["key"],
                    url=url,
                    reason=result.error,
                    theme="platform_attention",
                )
                series.append(
                    {
                        "market": market.code,
                        "entity": entity["key"],
                        "qid": entity["qid"],
                        "channel": entity["channel"],
                        "project": market.wiki_project,
                        "title": title,
                        "url": url,
                        "ok": False,
                        "reason": result.error,
                        "items": [],
                    }
                )
                continue
            try:
                payload = json.loads(result.body.decode("utf-8"))
            except json.JSONDecodeError as exc:
                record_failure(
                    run_id,
                    source="wikimedia_pageviews",
                    market=market.code,
                    entity=entity["key"],
                    url=url,
                    reason=f"invalid JSON: {exc}",
                    theme="platform_attention",
                )
                continue
            items = [
                {"timestamp": item.get("timestamp"), "views": item.get("views")}
                for item in payload.get("items") or []
                if isinstance(item, dict)
            ]
            series.append(
                {
                    "market": market.code,
                    "entity": entity["key"],
                    "qid": entity["qid"],
                    "channel": entity["channel"],
                    "project": market.wiki_project,
                    "title": title,
                    "url": result.url,
                    "ok": True,
                    "items": items,
                }
            )
    ok_series = sum(1 for row in series if row.get("ok"))
    return {
        "source": "wikimedia_pageviews",
        "pulled_at": iso_now(),
        "run_id": run_id,
        "docs": "https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/",
        "window": window,
        "hong_kong_project": "zh-yue.wikipedia",
        "china_project": "zh.wikipedia",
        "entities": [
            {
                "qid": entity["qid"],
                "key": entity["key"],
                "channel": entity["channel"],
                "accepted": entity["accepted"],
                "description": entity.get("description"),
                "titles": entity.get("titles"),
            }
            for entity in entities
        ],
        "series_ok": ok_series,
        "series_rows": len(series),
        "ok": ok_series > 0,
        "series": series,
    }
