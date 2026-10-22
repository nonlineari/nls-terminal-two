"""Proxy training label. This is not observed campaign ROI.

The label is a comparable index built only from public macro series plus the
within-market mix of Wikipedia pageviews. See FORMULA_TEXT.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from src.features.series import minmax_dict

# Base weights. If a component is missing for any eligible market, that
# component is dropped and these weights are renormalized to 1.
OPPORTUNITY_WEIGHTS: dict[str, float] = {
    "reach": 0.40,
    "momentum": 0.25,
    "demo": 0.20,
    "cost_access": 0.15,
}

# Convex combination: even a channel with no pageviews would score the floor,
# but a missing share does not get the floor — the row is left unlabeled.
ATTENTION_FLOOR = 0.35
ATTENTION_WEIGHT = 0.65

FORMULA_TEXT = """
proxy_return = opportunity * (0.35 + 0.65 * channel_attention_share)

opportunity =
    0.40 * minmax(log(internet_users))
  + 0.25 * minmax(internet_user_cagr)
  + 0.20 * minmax(share of population ages 0-14)
  + 0.15 * (1 - minmax(log(gdp_per_capita_usd)))

internet_users = population * (internet users % / 100) on the latest year
where both World Bank series are present. CAGR uses that constructed series
from the earliest to the latest overlapping year, and only if the span is at
least 3 years.

Ages 0-14 stand in for a youth audience because the World Bank API rejected
the 15-24 indicator id SP.POP.1524.TO.ZS. It is not the 15-24 music demographic.

If CAGR or the age share is missing for any eligible market, that component is
dropped and the remaining weights are renormalized to 1. A market is eligible
only when internet_users and gdp_per_capita are both positive.

channel_attention_share is the last-12-month share of local-Wikipedia
pageviews among streaming DSP, short video, and social/influencer articles.
It is an attention proxy, not a measured return. If the share is missing, the
row has no proxy label and is not used for training.

Min-max is fit on the eligible markets in the same run only. The result is a
unitless index, not revenue per dollar and not an NLS profit figure.
""".strip()


@dataclass
class OpportunityResult:
    scores: dict[str, float | None]
    eligible: list[str]
    active_weights: dict[str, float]
    components: dict[str, dict[str, float | None]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _finite(value: float | None) -> bool:
    return value is not None and isinstance(value, (int, float)) and math.isfinite(float(value))


def _log(value: float) -> float:
    return math.log(float(value))


def build_opportunity(
    internet_users: dict[str, float | None],
    internet_user_cagr: dict[str, float | None],
    share_age_0_14: dict[str, float | None],
    gdp_per_capita: dict[str, float | None],
) -> OpportunityResult:
    """Return the market opportunity index and the components that entered it."""
    weight_sum = sum(OPPORTUNITY_WEIGHTS.values())
    if not math.isclose(weight_sum, 1.0, abs_tol=1e-9):
        raise ValueError(f"opportunity weights sum to {weight_sum}, not 1")
    if not math.isclose(ATTENTION_FLOOR + ATTENTION_WEIGHT, 1.0, abs_tol=1e-9):
        raise ValueError("attention floor and weight must sum to 1")

    markets = sorted(
        set(internet_users) | set(internet_user_cagr) | set(share_age_0_14) | set(gdp_per_capita)
    )
    eligible = [
        market
        for market in markets
        if _finite(internet_users.get(market))
        and float(internet_users[market]) > 0
        and _finite(gdp_per_capita.get(market))
        and float(gdp_per_capita[market]) > 0
    ]
    notes: list[str] = []
    if not eligible:
        notes.append("No market had both internet users and GDP per capita.")
        return OpportunityResult(
            scores={market: None for market in markets},
            eligible=[],
            active_weights={},
            notes=notes,
        )

    raw: dict[str, dict[str, float]] = {
        "reach": {market: _log(float(internet_users[market])) for market in eligible},
        "cost": {market: _log(float(gdp_per_capita[market])) for market in eligible},
    }
    optional = {
        "momentum": internet_user_cagr,
        "demo": share_age_0_14,
    }
    active = ["reach", "cost_access"]
    for name, source in optional.items():
        if all(_finite(source.get(market)) for market in eligible):
            raw[name] = {market: float(source[market]) for market in eligible}
            active.append(name)
        else:
            notes.append(
                f"Dropped {name} from the opportunity index because it was missing "
                "for at least one eligible market."
            )

    scaled = {
        "reach": minmax_dict(raw["reach"]),
        "cost_access": {
            market: 1.0 - value for market, value in minmax_dict(raw["cost"]).items()
        },
    }
    if "momentum" in raw:
        scaled["momentum"] = minmax_dict(raw["momentum"])
    if "demo" in raw:
        scaled["demo"] = minmax_dict(raw["demo"])

    active_weights_raw = {name: OPPORTUNITY_WEIGHTS[name] for name in active}
    denom = sum(active_weights_raw.values())
    active_weights = {name: weight / denom for name, weight in active_weights_raw.items()}

    scores: dict[str, float | None] = {market: None for market in markets}
    components: dict[str, dict[str, float | None]] = {market: {} for market in markets}
    for market in eligible:
        total = 0.0
        for name, weight in active_weights.items():
            component = scaled[name][market]
            components[market][name] = component
            total += weight * component
        scores[market] = total
    return OpportunityResult(
        scores=scores,
        eligible=eligible,
        active_weights=active_weights,
        components=components,
        notes=notes,
    )


def proxy_return(opportunity: float | None, attention_share: float | None) -> float | None:
    """Scale a market opportunity score by that row's channel attention share."""
    if opportunity is None or attention_share is None:
        return None
    if not math.isfinite(opportunity) or not math.isfinite(attention_share):
        return None
    if attention_share < 0 or attention_share > 1:
        raise ValueError(f"attention share out of range: {attention_share}")
    return float(opportunity) * (ATTENTION_FLOOR + ATTENTION_WEIGHT * float(attention_share))
