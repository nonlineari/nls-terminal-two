"""Confidence weights and budget splits. Pure functions, no model object."""

from __future__ import annotations

import math

CONFIDENCE_CAP = 0.85


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def confidence_score(completeness: float, separation: float, error_penalty: float) -> float:
    """Trust weight in [0.05, 0.85].

    completeness: share of model fields that were observed for the row.
    separation: std(prediction) / std(label) across the LOOCV pool, clipped to [0, 1].
        A model that predicts a constant gets no credit here.
    error_penalty: 1 when the row's absolute LOOCV error is 0, 0 when it exceeds
        MAE + RMSE.

    The weights plus the 0.05 floor sum to 0.85. The cap stays even if a later
    caller passes values above 1, because the label is not observed ROI.
    """
    raw = (
        0.05
        + 0.25 * _clip(completeness, 0.0, 1.0)
        + 0.35 * _clip(separation, 0.0, 1.0)
        + 0.20 * _clip(error_penalty, 0.0, 1.0)
    )
    return float(min(raw, CONFIDENCE_CAP))


def error_penalty(abs_error: float, mae: float, rmse: float) -> float:
    scale = float(mae) + float(rmse)
    if scale <= 1e-12:
        return 1.0
    return 1.0 - _clip(abs_error / scale, 0.0, 1.0)


def separation_ratio(predictions: list[float], labels: list[float]) -> float:
    if len(predictions) < 2 or len(labels) < 2:
        return 0.0
    pred_std = _std(predictions)
    label_std = _std(labels)
    if label_std <= 1e-12:
        return 0.0
    return _clip(pred_std / label_std, 0.0, 1.0)


def _std(values: list[float]) -> float:
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def percent_split(weights: list[float]) -> list[float]:
    """Largest-remainder split in 0.01 percentage-point units. Sums to 100."""
    if not weights:
        return []
    total = sum(max(0.0, weight) for weight in weights)
    if total <= 0:
        raw = [100.0 / len(weights)] * len(weights)
    else:
        raw = [100.0 * max(0.0, weight) / total for weight in weights]
    return _largest_remainder(raw, target_units=10000)


def _largest_remainder(raw_percents: list[float], target_units: int) -> list[float]:
    units = [int(math.floor(value * 100 + 1e-8)) for value in raw_percents]
    deficit = target_units - sum(units)
    fractions = [value * 100 - units[index] for index, value in enumerate(raw_percents)]
    if deficit > 0:
        order = sorted(range(len(raw_percents)), key=lambda i: (fractions[i], -i), reverse=True)
        for step in range(deficit):
            units[order[step % len(units)]] += 1
    elif deficit < 0:
        order = sorted(range(len(raw_percents)), key=lambda i: (fractions[i], i))
        for step in range(-deficit):
            index = order[step % len(units)]
            if units[index] > 0:
                units[index] -= 1
    return [unit / 100.0 for unit in units]


def money_split(budget: float, percents: list[float]) -> list[float]:
    """Split `budget` in cent units so the pieces sum to the cent-rounded budget."""
    if not percents:
        return []
    raw = [budget * percent / 100.0 for percent in percents]
    cents = [int(math.floor(value * 100 + 1e-8)) for value in raw]
    target = int(round(budget * 100))
    deficit = target - sum(cents)
    fractions = [value * 100 - cents[index] for index, value in enumerate(raw)]
    if deficit > 0:
        order = sorted(range(len(raw)), key=lambda i: (fractions[i], -i), reverse=True)
        for step in range(deficit):
            cents[order[step % len(cents)]] += 1
    elif deficit < 0:
        order = sorted(range(len(raw)), key=lambda i: (fractions[i], i))
        for step in range(-deficit):
            index = order[step % len(cents)]
            if cents[index] > 0:
                cents[index] -= 1
    return [cent / 100.0 for cent in cents]


def allocate_groups(
    groups: list[list[dict]],
    budget: float,
) -> list[dict]:
    """Allocate budget across groups, then split each group equally across its rows.

    Each group is a list of row dicts. The group's weight is
    max(first row pred, 0) * first row confidence. That weight is divided
    equally across the rows in the group, then all rows are percent-split
    together so the shares sum to 100 and the amounts sum to the budget.

    In channel mode every row is its own group. In market-only mode the three
    channels share one group, so a market is not triple-counted.
    """
    if budget <= 0:
        raise ValueError("budget must be positive")
    flat_rows: list[dict] = []
    flat_weights: list[float] = []
    for members in groups:
        if not members:
            raise ValueError("empty allocation group")
        pred = float(members[0]["pred"])
        confidence = float(members[0]["confidence"])
        group_weight = max(pred, 0.0) * max(confidence, 0.0)
        share = group_weight / len(members)
        for member in members:
            flat_rows.append(dict(member))
            flat_weights.append(share)
    percents = percent_split(flat_weights)
    amounts = money_split(budget, percents)
    for row, percent, amount in zip(flat_rows, percents, amounts):
        row["percent"] = percent
        row["amount"] = amount
    return flat_rows
