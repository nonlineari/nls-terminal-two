"""Shared numeric transforms. No network, no fabricated measurements."""

from __future__ import annotations

import math


def year_map(points: list[tuple[int, float]]) -> dict[int, float]:
    out: dict[int, float] = {}
    for year, value in points:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            continue
        out[int(year)] = float(value)
    return out


def latest_positive(values: dict[int, float]) -> tuple[int | None, float | None]:
    points = [(year, value) for year, value in values.items() if value is not None and value > 0]
    if not points:
        return None, None
    return max(points)


def cagr_from_year_map(
    values: dict[int, float],
    min_span: int = 3,
) -> tuple[float | None, int | None, int | None]:
    """Compound annual growth between the earliest and latest positive points.

    Returns (cagr, start_year, end_year). The span must cover at least
    `min_span` calendar years. A shorter window returns a null CAGR rather
    than a one-year blip presented as a trend.
    """
    points = sorted(
        (year, value) for year, value in values.items() if value is not None and value > 0
    )
    if len(points) < 2:
        return None, None, None
    start_year, start_value = points[0]
    end_year, end_value = points[-1]
    span = end_year - start_year
    if span < min_span:
        return None, start_year, end_year
    return (end_value / start_value) ** (1.0 / span) - 1.0, start_year, end_year


def internet_user_series(
    population: dict[int, float],
    internet_pct: dict[int, float],
) -> dict[int, float]:
    """People online ≈ population × internet-user percent / 100, on shared years."""
    out: dict[int, float] = {}
    for year in set(population) & set(internet_pct):
        pop = population[year]
        pct = internet_pct[year]
        if pop is None or pct is None or pop <= 0 or pct < 0:
            continue
        out[year] = pop * pct / 100.0
    return out


def minmax_dict(values: dict[str, float]) -> dict[str, float]:
    """Min-max across the provided markets. A constant series maps to 0.5."""
    if not values:
        return {}
    low = min(values.values())
    high = max(values.values())
    if math.isclose(high, low):
        return {key: 0.5 for key in values}
    scale = high - low
    return {key: (value - low) / scale for key, value in values.items()}
