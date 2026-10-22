"""Indie accessibility: a relative heuristic, not an industry index.

Higher means a non-local or independent release has more structural room to
reach listeners in this seven-market set: broader connectivity, a younger age
structure, lower income-linked media prices, and a less concentrated set of
local-language streaming articles.

The score is min-maxed inside the run (except platform diversity, which is
already a 0–1 Hirschman-Herfindahl complement). It is reported in the feature
matrix and is not a model input, because several ingredients also enter the
proxy label.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from src.config import MOBILE_SATURATION_PER_100
from src.features.series import minmax_dict

INDIE_WEIGHTS: dict[str, float] = {
    "internet": 0.24,
    "mobile": 0.16,
    "broadband": 0.12,
    "young_share": 0.13,
    "cost_access": 0.15,
    "platform_diversity": 0.20,
}


@dataclass
class IndieResult:
    scores: dict[str, float | None]
    active_weights: dict[str, float]
    notes: list[str] = field(default_factory=list)


def _finite(value: float | None) -> bool:
    return value is not None and isinstance(value, (int, float)) and math.isfinite(float(value))


def indie_scores(
    internet_pct: dict[str, float | None],
    mobile_per_100: dict[str, float | None],
    broadband_per_100: dict[str, float | None],
    share_age_0_14: dict[str, float | None],
    gdp_per_capita: dict[str, float | None],
    platform_diversity: dict[str, float | None],
) -> IndieResult:
    weight_sum = sum(INDIE_WEIGHTS.values())
    if not math.isclose(weight_sum, 1.0, abs_tol=1e-9):
        raise ValueError(f"indie weights sum to {weight_sum}, not 1")

    markets = sorted(
        set(internet_pct)
        | set(mobile_per_100)
        | set(broadband_per_100)
        | set(share_age_0_14)
        | set(gdp_per_capita)
        | set(platform_diversity)
    )
    notes = [
        f"Mobile subscriptions per 100 people are capped at {MOBILE_SATURATION_PER_100:.0f} "
        "before scaling. Values above that are treated as multi-SIM saturation."
    ]
    if not markets:
        return IndieResult(scores={}, active_weights={}, notes=notes)

    mobile_capped = {
        market: min(float(value), MOBILE_SATURATION_PER_100)
        for market, value in mobile_per_100.items()
        if _finite(value)
    }
    cost_raw = {
        market: math.log(float(value))
        for market, value in gdp_per_capita.items()
        if _finite(value) and float(value) > 0
    }
    candidates: dict[str, dict[str, float]] = {
        "internet": {m: float(v) for m, v in internet_pct.items() if _finite(v)},
        "mobile": mobile_capped,
        "broadband": {m: float(v) for m, v in broadband_per_100.items() if _finite(v)},
        "young_share": {m: float(v) for m, v in share_age_0_14.items() if _finite(v)},
        "cost_access": cost_raw,
        "platform_diversity": {
            m: float(v) for m, v in platform_diversity.items() if _finite(v)
        },
    }

    active: list[str] = []
    scaled: dict[str, dict[str, float]] = {}
    for name, values in candidates.items():
        if len(values) < len(markets):
            notes.append(
                f"Dropped {name} from the indie score because it was missing for at least one market."
            )
            continue
        active.append(name)
        if name == "platform_diversity":
            # Already a 0–1 concentration complement. Do not re-stretch it.
            scaled[name] = values
        elif name == "cost_access":
            scaled[name] = {
                market: 1.0 - value for market, value in minmax_dict(values).items()
            }
        else:
            scaled[name] = minmax_dict(values)

    if not active:
        notes.append("Indie score is null: no component was complete across markets.")
        return IndieResult(
            scores={market: None for market in markets},
            active_weights={},
            notes=notes,
        )

    denom = sum(INDIE_WEIGHTS[name] for name in active)
    active_weights = {name: INDIE_WEIGHTS[name] / denom for name in active}
    scores: dict[str, float | None] = {}
    for market in markets:
        scores[market] = sum(
            active_weights[name] * scaled[name][market] for name in active
        )
    return IndieResult(scores=scores, active_weights=active_weights, notes=notes)
