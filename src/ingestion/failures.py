"""Append-only log of sources that did not yield usable territory numbers."""

from __future__ import annotations

import json
import logging

from src.config import FAILURES_PATH, iso_now
from src.jsonutil import jsonable

logger = logging.getLogger(__name__)


def record_failure(run_id: str, **fields: object) -> None:
    row = {"run_id": run_id, "logged_at": iso_now(), **fields}
    FAILURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FAILURES_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(jsonable(row), ensure_ascii=False) + "\n")
    logger.warning(
        "source failed: %s — %s",
        fields.get("source", "unknown"),
        fields.get("reason") or fields.get("error") or "no detail",
    )
