"""World Bank World Development Indicators. No key required."""

from __future__ import annotations

import json
import logging

from src.config import ISO_PATH, MARKETS, iso_now
from src.ingestion.failures import record_failure
from src.ingestion.http_util import fetch

logger = logging.getLogger(__name__)

API = "https://api.worldbank.org/v2"
# History is required for internet-user CAGR. Latest-only indicators are levels.
HISTORY_INDICATORS = ("SP.POP.TOTL", "IT.NET.USER.ZS")
LATEST_INDICATORS = (
    "NY.GDP.PCAP.CD",
    "NY.GDP.PCAP.PP.CD",
    "NY.GDP.MKTP.CD",
    "IT.CEL.SETS.P2",
    "IT.NET.BBND.P2",
    "SP.URB.TOTL.IN.ZS",
    "SP.POP.0014.TO.ZS",
    "SP.POP.1564.TO.ZS",
    "FP.CPI.TOTL.ZG",
    "PA.NUS.FCRF",
    "IT.NET.SECR.P6",
)
# The 15-24 share would be the better music-audience proxy. The API rejects this id.
PROBED_INDICATORS = ("SP.POP.1524.TO.ZS",)
HISTORY_RANGE = "2015:2025"
CORE_INDICATORS = ("SP.POP.TOTL", "IT.NET.USER.ZS", "NY.GDP.PCAP.CD")


def parse_year(value: object) -> int | None:
    if value is None:
        return None
    head = str(value)[:4]
    if head.isdigit():
        return int(head)
    return None


def rows_from_body(body: object) -> list[dict]:
    if not isinstance(body, list) or len(body) < 2 or not isinstance(body[1], list):
        return []
    return [row for row in body[1] if isinstance(row, dict)]


def series_by_iso3(rows: list[dict]) -> dict[str, list[tuple[int, float]]]:
    out: dict[str, list[tuple[int, float]]] = {market.iso3: [] for market in MARKETS}
    for row in rows:
        iso = row.get("countryiso3code")
        if iso not in out or row.get("value") is None:
            continue
        year = parse_year(row.get("date"))
        if year is None:
            continue
        out[iso].append((year, float(row["value"])))
    return out


def _is_error_payload(payload: object) -> bool:
    return (
        isinstance(payload, list)
        and bool(payload)
        and isinstance(payload[0], dict)
        and "message" in payload[0]
    )


def _fetch_pages(indicator: str, iso_path: str, *, history: bool) -> dict:
    params: dict[str, object] = {"format": "json", "per_page": 1000}
    if history:
        params["date"] = HISTORY_RANGE
    else:
        params["mrnev"] = 1
    url = f"{API}/country/{iso_path}/indicator/{indicator}"
    result = fetch(url, params=params, timeout=60, max_attempts=3)
    if not result.ok or result.body is None:
        return {"ok": False, "url": result.url, "error": result.error, "body": None, "history": history}
    try:
        payload = json.loads(result.body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        return {"ok": False, "url": result.url, "error": f"invalid JSON: {exc}", "body": None, "history": history}
    if _is_error_payload(payload):
        message = payload[0].get("message")
        return {
            "ok": False,
            "url": result.url,
            "error": f"World Bank error: {message}",
            "body": payload,
            "history": history,
        }
    if not isinstance(payload, list) or len(payload) < 2:
        return {"ok": False, "url": result.url, "error": "unexpected payload shape", "body": payload, "history": history}
    meta = payload[0] if isinstance(payload[0], dict) else {}
    pages = int(meta.get("pages") or 1)
    rows = list(payload[1] or [])
    for page in range(2, pages + 1):
        page_params = dict(params)
        page_params["page"] = page
        page_result = fetch(url, params=page_params, timeout=60, max_attempts=3)
        if not page_result.ok or page_result.body is None:
            return {
                "ok": False,
                "url": page_result.url,
                "error": f"page {page} failed: {page_result.error}",
                "body": None,
                "history": history,
            }
        page_payload = json.loads(page_result.body.decode("utf-8"))
        rows.extend(page_payload[1] or [])
    merged = [meta, rows]
    return {"ok": True, "url": result.url, "error": None, "body": merged, "history": history}


def _fetch_indicator(indicator: str, *, history: bool) -> dict:
    batch = _fetch_pages(indicator, ISO_PATH, history=history)
    if batch["ok"]:
        return batch
    logger.info("World Bank batch failed for %s; trying one country at a time", indicator)
    rows: list[dict] = []
    errors: list[str] = []
    url = ""
    for market in MARKETS:
        one = _fetch_pages(indicator, market.iso3, history=history)
        url = one.get("url") or url
        if not one["ok"]:
            errors.append(f"{market.iso3}: {one.get('error')}")
            continue
        rows.extend(rows_from_body(one.get("body")))
    if not rows:
        return {
            "ok": False,
            "url": url,
            "error": batch.get("error") or "; ".join(errors),
            "body": None,
            "history": history,
        }
    return {
        "ok": True,
        "url": url,
        "error": None,
        "body": [{"page": 1, "pages": 1, "total": len(rows), "note": "assembled per country"}, rows],
        "history": history,
        "partial_errors": errors,
    }


def _nonempty_markets(block: dict) -> int:
    if not block.get("ok"):
        return 0
    series = series_by_iso3(rows_from_body(block.get("body")))
    return sum(1 for points in series.values() if points)


def fetch_worldbank(run_id: str) -> dict:
    indicators: dict[str, dict] = {}
    for indicator in HISTORY_INDICATORS:
        logger.info("World Bank history %s", indicator)
        block = _fetch_indicator(indicator, history=True)
        indicators[indicator] = block
        if not block["ok"]:
            record_failure(
                run_id,
                source="worldbank",
                indicator=indicator,
                url=block.get("url"),
                reason=block.get("error"),
                theme="macro",
            )
    for indicator in LATEST_INDICATORS:
        logger.info("World Bank latest %s", indicator)
        block = _fetch_indicator(indicator, history=False)
        indicators[indicator] = block
        if not block["ok"]:
            record_failure(
                run_id,
                source="worldbank",
                indicator=indicator,
                url=block.get("url"),
                reason=block.get("error"),
                theme="macro",
            )
    for indicator in PROBED_INDICATORS:
        logger.info("World Bank probe %s (expected to be rejected)", indicator)
        block = _fetch_indicator(indicator, history=False)
        indicators[indicator] = block
        record_failure(
            run_id,
            source="worldbank",
            indicator=indicator,
            url=block.get("url"),
            reason=block.get("error") or "indicator returned no usable 15-24 series",
            theme="youth_age_share",
            note=(
                "SP.POP.1524.TO.ZS is not a valid World Bank indicator id. "
                "The pipeline keeps SP.POP.0014.TO.ZS and does not invent a 15-24 series."
            ),
        )
    core_counts = {indicator: _nonempty_markets(indicators[indicator]) for indicator in CORE_INDICATORS}
    core_ok = all(count >= 4 for count in core_counts.values())
    return {
        "source": "worldbank",
        "api": "https://api.worldbank.org/v2",
        "pulled_at": iso_now(),
        "run_id": run_id,
        "history_range": HISTORY_RANGE,
        "core_counts": core_counts,
        "core_ok": core_ok,
        "indicators": indicators,
    }
