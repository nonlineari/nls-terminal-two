"""Cost-aware reweight helpers for budget splits when CPM/CPC are present.

Without any positive rate on the allocation rows, every factor is 1.0 and
``allocate_groups`` behavior is unchanged. When at least one row has a
positive CPM (preferred) or CPC, that row's allocation weight is multiplied
by a relative efficiency factor: cheaper inventory gets a higher share.

Efficiency for a row with cost ``c`` among the set of observed costs is
``median(costs) / c``. Rows with no rate keep factor 1.0 so they are neither
boosted nor penalized relative to the pre-rate baseline weight.
"""

from __future__ import annotations

import math
from statistics import median
from typing import Sequence


def cost_efficiency_factors(
    cpm_values: Sequence[float | None],
    cpc_values: Sequence[float | None] | None = None,
) -> list[float]:
    """Return per-row multipliers for ``pred * confidence`` weights.

    Prefers CPM when any positive CPM exists; otherwise falls back to CPC.
    Length of the result matches ``cpm_values``.
    """
    n = len(cpm_values)
    if n == 0:
        return []
    cpc_values = list(cpc_values) if cpc_values is not None else [None] * n
    if len(cpc_values) != n:
        raise ValueError("cpm_values and cpc_values must have the same length")

    cpm_present = [float(v) for v in cpm_values if v is not None and float(v) > 0]
    if cpm_present:
        return _factors_from_costs(cpm_values, cpm_present)

    cpc_present = [float(v) for v in cpc_values if v is not None and float(v) > 0]
    if cpc_present:
        return _factors_from_costs(cpc_values, cpc_present)

    return [1.0] * n


def _factors_from_costs(
    values: Sequence[float | None],
    present: list[float],
) -> list[float]:
    center = median(present)
    if center <= 0 or not math.isfinite(center):
        return [1.0] * len(values)
    factors: list[float] = []
    for value in values:
        if value is None or float(value) <= 0 or not math.isfinite(float(value)):
            factors.append(1.0)
        else:
            factors.append(center / float(value))
    return factors


def apply_cost_factors_to_pred(
    pred: float,
    confidence: float,
    cost_factor: float,
) -> float:
    """Adjusted score used as the group weight numerator before percent_split."""
    return max(float(pred), 0.0) * max(float(confidence), 0.0) * max(float(cost_factor), 0.0)
