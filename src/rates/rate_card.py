"""Load market × channel CPM/CPC from a local rate-card JSON.

Expected JSON shape (also in ``config/rate_card.example.json``)::

    {
      "enabled": true,
      "currency": "USD",
      "source": "human-readable origin of the numbers",
      "rates": [
        {
          "market_code": "KR",
          "channel": "short_video",
          "cpm_usd": 4.5,
          "cpc_usd": 0.35
        }
      ]
    }

How to enable
-------------
1. Copy ``config/rate_card.example.json`` to ``config/rate_card.json``
   (or any path), replace EXAMPLE values with authorized rates, set
   ``"enabled": true``.
2. Point ``NLS_RATE_CARD_PATH`` at that file (optional if using the
   default ``config/rate_card.json``).
3. Rebuild features: ``python3 -m src.features.build``.

Credential stubs
----------------
``NLS_AD_PLATFORM_API_KEY`` / ``NLS_AD_PLATFORM_API_SECRET`` are recognized
as placeholders for a future ad-platform pull. They do **not** fetch or
invent rates today. If a key is set but no enabled rate-card file is found,
the loader logs that the API path is unimplemented and leaves rates null.

When no file / credentials: log once and return an empty card. Callers leave
``ad_cpm_usd_observed`` / ``ad_cpc_usd_observed`` null.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.config import CHANNELS, MARKET_BY_CODE, RATE_CARD_DEFAULT_PATH, ROOT
from src.jsonutil import read_json

logger = logging.getLogger(__name__)

ENV_RATE_CARD_PATH = "NLS_RATE_CARD_PATH"
ENV_API_KEY = "NLS_AD_PLATFORM_API_KEY"
ENV_API_SECRET = "NLS_AD_PLATFORM_API_SECRET"


@dataclass(frozen=True)
class RateLookup:
    """CPM/CPC for one market × channel. Either field may be None."""

    cpm_usd: float | None = None
    cpc_usd: float | None = None


@dataclass(frozen=True)
class RateCard:
    """In-memory rate card. Empty cards mean every lookup is null."""

    enabled: bool = False
    currency: str = "USD"
    source: str = ""
    path: str | None = None
    # (market_code, channel) -> RateLookup
    by_key: dict[tuple[str, str], RateLookup] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def populated(self) -> bool:
        return bool(self.by_key)


def rates_for(card: RateCard | None, market_code: str, channel: str) -> RateLookup:
    if card is None or not card.populated:
        return RateLookup()
    return card.by_key.get((market_code, channel), RateLookup())


def load_rate_card(path: Path | str | None = None) -> RateCard:
    """Resolve and load a rate card, or return an empty card.

    Resolution order:
    1. Explicit ``path`` argument.
    2. ``NLS_RATE_CARD_PATH`` environment variable.
    3. Default ``config/rate_card.json`` under the repo root (not the example).
    """
    resolved = _resolve_path(path)
    api_key_set = bool(os.environ.get(ENV_API_KEY) or os.environ.get(ENV_API_SECRET))

    if resolved is None:
        note = "No rate-card file configured; CPM/CPC columns stay null."
        if api_key_set:
            note = (
                f"{ENV_API_KEY} is set, but ad-platform fetch is not implemented. "
                "Supply an enabled rate-card JSON via NLS_RATE_CARD_PATH "
                f"or {RATE_CARD_DEFAULT_PATH.relative_to(ROOT)}. CPM/CPC stay null."
            )
        logger.info("%s", note)
        return RateCard(notes=(note,))

    if not resolved.exists():
        note = f"Rate-card path does not exist: {resolved}. CPM/CPC stay null."
        logger.warning("%s", note)
        return RateCard(path=str(resolved), notes=(note,))

    try:
        payload = read_json(resolved)
    except (OSError, ValueError) as exc:
        note = f"Failed to read rate card {resolved}: {exc}. CPM/CPC stay null."
        logger.warning("%s", note)
        return RateCard(path=str(resolved), notes=(note,))

    return _parse_payload(payload, resolved)


def _resolve_path(path: Path | str | None) -> Path | None:
    if path is not None:
        return Path(path)
    env = os.environ.get(ENV_RATE_CARD_PATH, "").strip()
    if env:
        return Path(env)
    if RATE_CARD_DEFAULT_PATH.exists():
        return RATE_CARD_DEFAULT_PATH
    return None


def _parse_payload(payload: Any, path: Path) -> RateCard:
    if not isinstance(payload, dict):
        note = f"Rate card at {path} is not a JSON object. CPM/CPC stay null."
        logger.warning("%s", note)
        return RateCard(path=str(path), notes=(note,))

    enabled = bool(payload.get("enabled", False))
    currency = str(payload.get("currency") or "USD")
    source = str(payload.get("source") or "")
    raw_rates = payload.get("rates")

    if not enabled:
        note = (
            f"Rate card at {path} has enabled=false; ignoring entries. "
            "CPM/CPC stay null."
        )
        logger.info("%s", note)
        return RateCard(
            enabled=False,
            currency=currency,
            source=source,
            path=str(path),
            notes=(note,),
        )

    if not isinstance(raw_rates, list):
        note = f"Rate card at {path} has no rates list. CPM/CPC stay null."
        logger.warning("%s", note)
        return RateCard(
            enabled=True,
            currency=currency,
            source=source,
            path=str(path),
            notes=(note,),
        )

    by_key: dict[tuple[str, str], RateLookup] = {}
    notes: list[str] = []
    for index, entry in enumerate(raw_rates):
        parsed = _parse_entry(entry, index, notes)
        if parsed is None:
            continue
        market_code, channel, lookup = parsed
        by_key[(market_code, channel)] = lookup

    if not by_key:
        notes.append("No valid market×channel rates after parsing; CPM/CPC stay null.")
        logger.info("%s", notes[-1])
    else:
        logger.info(
            "Loaded %s rate-card rows from %s (source=%s)",
            len(by_key),
            path,
            source or "unspecified",
        )

    return RateCard(
        enabled=True,
        currency=currency,
        source=source,
        path=str(path),
        by_key=by_key,
        notes=tuple(notes),
    )


def _parse_entry(
    entry: Any,
    index: int,
    notes: list[str],
) -> tuple[str, str, RateLookup] | None:
    if not isinstance(entry, dict):
        notes.append(f"rates[{index}] is not an object; skipped.")
        return None
    market_code = str(entry.get("market_code") or "").strip().upper()
    channel = str(entry.get("channel") or "").strip()
    if market_code not in MARKET_BY_CODE:
        notes.append(f"rates[{index}] unknown market_code={market_code!r}; skipped.")
        return None
    if channel not in CHANNELS:
        notes.append(
            f"rates[{index}] channel={channel!r} is not a scored channel "
            f"({', '.join(CHANNELS)}); skipped. Sync/paid_social stay unscored."
        )
        return None
    cpm = _optional_positive_float(entry.get("cpm_usd"), f"rates[{index}].cpm_usd", notes)
    cpc = _optional_positive_float(entry.get("cpc_usd"), f"rates[{index}].cpc_usd", notes)
    if cpm is None and cpc is None:
        notes.append(f"rates[{index}] has neither cpm_usd nor cpc_usd; skipped.")
        return None
    return market_code, channel, RateLookup(cpm_usd=cpm, cpc_usd=cpc)


def _optional_positive_float(value: Any, label: str, notes: list[str]) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        notes.append(f"{label}={value!r} is not a number; treated as null.")
        return None
    if number != number or number <= 0:  # NaN or non-positive
        notes.append(f"{label}={value!r} must be a positive number; treated as null.")
        return None
    return number
