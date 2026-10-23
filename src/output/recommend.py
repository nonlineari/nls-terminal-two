"""Print rankings and a budget split from the saved model and LOOCV scores."""

from __future__ import annotations

import logging

import joblib
import pandas as pd

from src.config import (
    FEATURE_MATRIX_PATH,
    METRICS_PATH,
    MODEL_PATH,
    PREDICTIONS_PATH,
    UNSCORED_CHANNELS,
)
from src.jsonutil import read_json
from src.output.scoring import allocate_groups
from src.rates.cost_adjust import cost_efficiency_factors

logger = logging.getLogger(__name__)


def _load_model_and_check() -> dict:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Missing {MODEL_PATH.name}. Run: python -m src.model.train")
    artifact = joblib.load(MODEL_PATH)
    models = artifact.get("models") or []
    features = artifact.get("model_features") or []
    if not models or not features:
        raise RuntimeError("Model artifact is missing models or feature names.")
    if not FEATURE_MATRIX_PATH.exists():
        raise FileNotFoundError(f"Missing {FEATURE_MATRIX_PATH.name}.")
    frame = pd.read_csv(FEATURE_MATRIX_PATH)
    missing = [name for name in features if name not in frame.columns]
    if missing:
        raise RuntimeError(f"Feature matrix does not match the model: {missing}")
    # Loading is not enough: run one predict so a broken artifact fails here.
    models[0].predict(frame[features].astype(float))
    return artifact


def _as_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes"}
    return bool(value)



def _finite_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number <= 0:  # NaN or non-positive
        return None
    return number


def _rate_lookup_from_matrix() -> dict[tuple[str, str], tuple[float | None, float | None]]:
    """Map (market_code, channel) -> (cpm, cpc) from the feature matrix."""
    if not FEATURE_MATRIX_PATH.exists():
        return {}
    frame = pd.read_csv(FEATURE_MATRIX_PATH)
    if "market_code" not in frame.columns or "channel" not in frame.columns:
        return {}
    out: dict[tuple[str, str], tuple[float | None, float | None]] = {}
    for row in frame.itertuples(index=False):
        cpm = _finite_or_none(getattr(row, "ad_cpm_usd_observed", None))
        cpc = _finite_or_none(getattr(row, "ad_cpc_usd_observed", None))
        out[(str(row.market_code), str(row.channel))] = (cpm, cpc)
    return out


def run_recommend(budget: float) -> int:
    if not PREDICTIONS_PATH.exists():
        logger.error("Missing %s. Run: python -m src.model.train", PREDICTIONS_PATH)
        return 1
    try:
        artifact = _load_model_and_check()
    except (FileNotFoundError, RuntimeError) as exc:
        logger.error("%s", exc)
        return 1
    predictions = pd.read_csv(PREDICTIONS_PATH)
    required = {"market_code", "market_name", "channel", "channel_label", "allocation_group", "pred_loocv", "confidence", "channel_informed"}
    missing = required - set(predictions.columns)
    if missing:
        logger.error("Prediction file is missing columns: %s", ", ".join(sorted(missing)))
        return 1
    metrics = read_json(METRICS_PATH) if METRICS_PATH.exists() else {}
    rate_lookup = _rate_lookup_from_matrix()
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    staged: list[dict] = []
    for row in predictions.itertuples(index=False):
        group = str(row.allocation_group)
        if group not in groups:
            order.append(group)
            groups[group] = []
        cpm, cpc = rate_lookup.get((str(row.market_code), str(row.channel)), (None, None))
        entry = {
            "market_code": row.market_code,
            "market_name": row.market_name,
            "channel": row.channel,
            "channel_label": row.channel_label,
            "pred": float(row.pred_loocv),
            "confidence": float(row.confidence),
            "channel_informed": _as_bool(row.channel_informed),
            "ad_cpm_usd_observed": cpm,
            "ad_cpc_usd_observed": cpc,
        }
        groups[group].append(entry)
        staged.append(entry)
    factors = cost_efficiency_factors(
        [item["ad_cpm_usd_observed"] for item in staged],
        [item["ad_cpc_usd_observed"] for item in staged],
    )
    rates_applied = any(factor != 1.0 for factor in factors)
    for item, factor in zip(staged, factors):
        item["cost_factor"] = factor
    allocated = allocate_groups([groups[key] for key in order], budget)
    allocated.sort(key=lambda row: (-row["pred"], -row["confidence"], row["market_name"], row["channel"]))
    channel_informed = _as_bool(predictions["channel_informed"].iloc[0])
    r2 = (metrics.get("loocv") or {}).get("r2")
    lines = [
        "Terminal Two — promo budget recommendation",
        f"Budget entered: {budget:,.2f} (one currency; not converted, not a revenue forecast)",
        "Ranking uses leave-one-market-out predictions of the proxy index.",
        f"Model artifact loaded: {MODEL_PATH.name} ({artifact.get('label_mode')}, ensemble of {len(artifact.get('models') or [])}).",
        "The proxy index is not observed return per dollar and not NLS campaign P&L.",
        f"Confidence is capped at 0.85. Formula inputs also used as features: channel attention share only.",
    ]
    if not channel_informed:
        lines.append(
            "Channel attention was missing, so each market's budget is split equally across the three channels."
        )
    if rates_applied:
        lines.append(
            "Cost-aware reweight is on: rows with rate-card CPM/CPC are scaled by "
            "median(cost)/cost (cheaper inventory gets a larger share). "
            "Rows without a rate keep factor 1.0."
        )
    elif any(item["ad_cpm_usd_observed"] is not None or item["ad_cpc_usd_observed"] is not None for item in staged):
        lines.append(
            "Rate-card CPM/CPC are present but relative costs did not change weights "
            "(single cost level or factors all 1.0)."
        )
    else:
        lines.append(
            "No rate-card CPM/CPC loaded; allocation matches the pre-rate-card split."
        )
    if r2 is not None and r2 < 0:
        lines.append(
            f"Leave-one-market-out R² is {r2:.3f}. The model does not beat a flat line out of sample. "
            "Treat the split as a low-confidence illustration."
        )
        if "y_true" in predictions.columns:
            lines.append(
                "The proxy formula itself ranks different rows highest. That formula is still not observed ROI:"
            )
            top = predictions.sort_values("y_true", ascending=False).head(5)
            for index, row in enumerate(top.itertuples(index=False), start=1):
                lines.append(
                    f"  {index}. {row.market_name} / {row.channel_label}: label {row.y_true:.3f}, "
                    f"model {row.pred_loocv:.3f}"
                )
    lines.append("")
    header = f"{'#':>2}  {'Market':<12} {'Channel':<22} {'Proxy':>8} {'Conf':>6} {'Share':>7} {'Amount':>14}"
    lines.append(header)
    lines.append("-" * len(header))
    for rank, row in enumerate(allocated, start=1):
        lines.append(
            f"{rank:>2}  {row['market_name']:<12} {row['channel_label']:<22} "
            f"{row['pred']:8.3f} {row['confidence']:6.2f} {row['percent']:6.2f}% {row['amount']:14,.2f}"
        )
    share_sum = sum(row["percent"] for row in allocated)
    amount_sum = sum(row["amount"] for row in allocated)
    lines.append("-" * len(header))
    lines.append(f"{'':>2}  {'Total':<12} {'':<22} {'':>8} {'':>6} {share_sum:6.2f}% {amount_sum:14,.2f}")
    lines.append("")
    lines.append("Not scored, and not given a fabricated rate so they could be scored:")
    for name, reason in UNSCORED_CHANNELS.items():
        lines.append(f"- {name}: {reason}")
    for item in metrics.get("omitted_markets") or []:
        lines.append(f"- {item.get('market_code')}: {item.get('reason')}")
    lines.append("")
    lines.append("Detail: python -m src.cli report    Metrics file: models/metrics.json")
    print("\n".join(lines))
    return 0


def run_report() -> int:
    if not METRICS_PATH.exists():
        logger.error("Missing %s. Run: python -m src.model.train", METRICS_PATH)
        return 1
    metrics = read_json(METRICS_PATH)
    loocv = metrics.get("loocv") or {}
    base = metrics.get("loocv_mean_baseline") or {}
    print("Terminal Two — model report")
    print(f"Label mode: {metrics.get('label_mode')}")
    print(f"Validation: {metrics.get('validation')}")
    print(
        "LOOCV  n={n}  MAE={mae}  RMSE={rmse}  R2={r2}".format(
            n=loocv.get("n"),
            mae=_fmt(loocv.get("mae")),
            rmse=_fmt(loocv.get("rmse")),
            r2=_fmt(loocv.get("r2")),
        )
    )
    print(
        "Baseline (train-fold mean)  MAE={mae}  RMSE={rmse}  R2={r2}".format(
            mae=_fmt(base.get("mae")),
            rmse=_fmt(base.get("rmse")),
            r2=_fmt(base.get("r2")),
        )
    )
    insample = metrics.get("insample_full_fit") or {}
    print(
        "In-sample full fit (optimistic)  MAE={mae}  R2={r2}".format(
            mae=_fmt(insample.get("mae")),
            r2=_fmt(insample.get("r2")),
        )
    )
    print(f"Separation (pred std / label std): {_fmt(metrics.get('separation'))}")
    print("Feature importance (mean gain share):")
    for row in metrics.get("feature_importances_gain") or []:
        print(f"  {row['share']:6.1%}  {row['feature']}")
    print("Limitations:")
    for item in metrics.get("limitations") or []:
        print(f"- {item}")
    return 0


def _fmt(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)
