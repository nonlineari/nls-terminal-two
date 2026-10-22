"""Pull public sources, cache the bodies, and keep going when one fails."""

from __future__ import annotations

import json
import logging

from src.config import (
    FAILURES_PATH,
    LATEST_RUN_PATH,
    MANIFEST_PATH,
    RAW_DIR,
    configure_logging,
    iso_now,
    new_run_id,
)
from src.ingestion.apple_charts import fetch_apple_charts
from src.ingestion.attempted import fetch_attempted
from src.ingestion.attention import fetch_attention
from src.ingestion.fx import fetch_fx
from src.ingestion.worldbank import fetch_worldbank
from src.jsonutil import write_json

logger = logging.getLogger(__name__)


def _relative(path) -> str:
    from src.config import ROOT

    return path.resolve().relative_to(ROOT).as_posix()


def _write(name: str, run_id: str, payload: dict):
    path = RAW_DIR / f"{name}_{run_id}.json"
    write_json(path, payload)
    logger.info("cached %s", path.name)
    return path


def _failures_for(run_id: str) -> list[dict]:
    if not FAILURES_PATH.exists():
        return []
    rows = []
    for line in FAILURES_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("run_id") == run_id:
            rows.append(row)
    return rows


def main() -> int:
    configure_logging()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    run_id = new_run_id()
    logger.info("ingestion run %s", run_id)

    worldbank = fetch_worldbank(run_id)
    frankfurter = fetch_fx(run_id)
    apple = fetch_apple_charts(run_id)
    attention = fetch_attention(run_id)
    attempted = fetch_attempted(run_id)

    paths = {
        "worldbank": _write("worldbank", run_id, worldbank),
        "frankfurter": _write("frankfurter", run_id, frankfurter),
        "apple_charts": _write("apple_charts", run_id, apple),
        "attention": _write("attention", run_id, attention),
        "attempted": _write("attempted", run_id, attempted),
    }
    apple_ok = int(apple.get("markets_ok") or 0)
    if not frankfurter.get("ok"):
        fx_status = "failed"
    elif frankfurter.get("missing_currencies"):
        fx_status = "partial"
    else:
        fx_status = "ok"
    status = {
        "worldbank": "ok" if worldbank.get("core_ok") else "failed",
        "frankfurter": fx_status,
        "apple_charts": "ok" if apple_ok == 7 else ("partial" if apple_ok else "failed"),
        "attention": "ok" if attention.get("ok") else "failed",
        "sync_licensing": "unavailable",
        "ad_cpm_cpc": "unavailable",
        "streaming_mau": "unavailable",
        "ifpi_territory_revenue": "unavailable",
    }
    manifest = {
        "run_id": run_id,
        "pulled_at": iso_now(),
        "files": {name: _relative(path) for name, path in paths.items()},
        "status": status,
        "worldbank_core_counts": worldbank.get("core_counts"),
        "apple_markets_ok": apple_ok,
        "attention_series_ok": attention.get("series_ok"),
    }
    failures = _failures_for(run_id)
    latest = {
        "run_id": run_id,
        "pulled_at": manifest["pulled_at"],
        "status": status,
        "failure_count": len(failures),
        "failures": failures,
        "files": manifest["files"],
    }
    write_json(MANIFEST_PATH, manifest)
    write_json(LATEST_RUN_PATH, latest)
    logger.info("manifest written (%s failure log rows this run)", len(failures))
    if not worldbank.get("core_ok"):
        logger.error(
            "Core World Bank series are missing (%s). Not inventing macro rows.",
            worldbank.get("core_counts"),
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
