"""ECB reference rates via Frankfurter. VND is not listed; that gap is logged."""

from __future__ import annotations

import json
import logging

from src.config import MARKETS, iso_now
from src.ingestion.failures import record_failure
from src.ingestion.http_util import fetch

logger = logging.getLogger(__name__)

SUPPORTED = ["KRW", "JPY", "IDR", "THB", "CNY", "HKD"]
API = "https://api.frankfurter.app/latest"


def fetch_fx(run_id: str) -> dict:
    url = f"{API}?from=USD&to={','.join(SUPPORTED)}"
    logger.info("Frankfurter USD crosses")
    result = fetch(url, timeout=30, max_attempts=3)
    rates: dict[str, float] = {}
    as_of = None
    error = None
    if result.ok and result.body:
        try:
            payload = json.loads(result.body.decode("utf-8"))
            as_of = payload.get("date")
            rates = {code: float(value) for code, value in (payload.get("rates") or {}).items()}
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            error = f"invalid JSON: {exc}"
            record_failure(run_id, source="frankfurter", url=result.url, reason=error, theme="fx")
    else:
        error = result.error
        record_failure(run_id, source="frankfurter", url=url, reason=error, theme="fx")

    vnd_url = f"{API}?from=USD&to=VND"
    vnd = fetch(vnd_url, timeout=30, max_attempts=2)
    vnd_rate = None
    vnd_error = None
    if vnd.ok and vnd.body:
        try:
            payload = json.loads(vnd.body.decode("utf-8"))
            raw = (payload.get("rates") or {}).get("VND")
            vnd_rate = float(raw) if raw is not None else None
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            vnd_error = str(exc)
    else:
        vnd_error = vnd.error or "VND not available"
    if vnd_rate is None:
        record_failure(
            run_id,
            source="frankfurter",
            url=vnd_url,
            reason=vnd_error,
            theme="fx",
            note="Vietnamese dong is not in the Frankfurter/ECB set. World Bank PA.NUS.FCRF is the VND series used in the matrix.",
        )
    else:
        rates["VND"] = vnd_rate

    by_market = {}
    for market in MARKETS:
        by_market[market.code] = rates.get(market.currency)
    return {
        "source": "frankfurter",
        "pulled_at": iso_now(),
        "run_id": run_id,
        "url": result.url if result else url,
        "ok": bool(rates),
        "date": as_of,
        "rates": rates,
        "by_market": by_market,
        "missing_currencies": [market.currency for market in MARKETS if market.currency not in rates],
        "error": error,
        "vnd_error": vnd_error,
        "docs": "https://www.frankfurter.app/docs/",
    }
