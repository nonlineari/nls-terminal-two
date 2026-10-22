"""Within-market attention math from Wikipedia pageview totals."""

from __future__ import annotations


def attention_shares(views_by_channel: dict[str, float | None]) -> dict[str, float | None]:
    """Share of pageviews across channels.

    A missing channel nulls every share. Renormalizing over the channels that
    happened to resolve would pretend the missing channel had zero attention.
    A present zero is a real zero and stays in the denominator.
    """
    if any(value is None for value in views_by_channel.values()):
        return {channel: None for channel in views_by_channel}
    total = sum(float(value) for value in views_by_channel.values())
    if total <= 0:
        return {channel: None for channel in views_by_channel}
    return {channel: float(value) / total for channel, value in views_by_channel.items()}


def hhi(values: list[float | None]) -> float | None:
    """Hirschman-Herfindahl index over positive observations. None if empty."""
    positive = [float(value) for value in values if value is not None and float(value) > 0]
    total = sum(positive)
    if total <= 0:
        return None
    return sum((value / total) ** 2 for value in positive)


def diversity_from_hhi(concentration: float | None) -> float | None:
    if concentration is None:
        return None
    return 1.0 - float(concentration)


def pageview_growth(last_12: float | None, prior_12: float | None, min_prior: float) -> float | None:
    """Year-over-year change. Null when the prior window is too small to ratio."""
    if last_12 is None or prior_12 is None:
        return None
    if prior_12 < min_prior:
        return None
    return float(last_12) / float(prior_12) - 1.0
