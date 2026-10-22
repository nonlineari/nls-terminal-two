"""Train a small XGBoost ensemble and score it with leave-one-market-out."""

from __future__ import annotations

import logging
from importlib.metadata import version

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from src.config import (
    FEATURE_MATRIX_PATH,
    MANIFEST_PATH,
    METADATA_PATH,
    METRICS_PATH,
    MODEL_PATH,
    MODELS_DIR,
    PREDICTIONS_PATH,
    SEED,
    configure_logging,
    iso_now,
)
from src.features.proxy_target import FORMULA_TEXT
from src.jsonutil import read_json, write_json
from src.model.spec import (
    COMPLETENESS_FIELDS,
    ENSEMBLE_SIZE,
    FORMULA_AND_MODEL,
    LIMITATIONS,
    MARKET_MODEL_FEATURES,
    MODEL_FEATURES,
    OPPORTUNITY_COLUMN,
    TARGET_COLUMN,
    WHY_XGBOOST,
    XGB_PARAMS,
)
from src.output.scoring import confidence_score, error_penalty, separation_ratio

logger = logging.getLogger(__name__)


def _fit(frame: pd.DataFrame, features: tuple[str, ...], seed: int, target: str):
    import xgboost as xgb

    params = dict(XGB_PARAMS)
    params["random_state"] = seed
    model = xgb.XGBRegressor(**params)
    model.fit(frame[list(features)].astype(float), frame[target].astype(float))
    return model


def _predict(model, frame: pd.DataFrame, features: tuple[str, ...]) -> np.ndarray:
    return np.asarray(model.predict(frame[list(features)].astype(float)), dtype=float)


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float | int | None]:
    if len(y_true) == 0:
        return {"n": 0, "mae": None, "rmse": None, "r2": None}
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    r2 = float(r2_score(y_true, y_pred)) if len(y_true) > 1 else None
    if r2 is not None and not np.isfinite(r2):
        r2 = None
    return {"n": int(len(y_true)), "mae": mae, "rmse": rmse, "r2": r2}


def _importances(models: list, features: tuple[str, ...]) -> list[dict[str, float | str]]:
    totals = {name: 0.0 for name in features}
    for model in models:
        score = model.get_booster().get_score(importance_type="gain")
        for name, value in score.items():
            if name in totals:
                totals[name] += float(value)
    mean = {name: totals[name] / len(models) for name in features}
    denom = sum(mean.values()) or 1.0
    ranked = sorted(mean.items(), key=lambda item: item[1], reverse=True)
    return [
        {"feature": name, "gain": value, "share": value / denom}
        for name, value in ranked
    ]


def _loocv(frame: pd.DataFrame, features: tuple[str, ...], target: str) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for market in frame["market_code"].drop_duplicates():
        test = frame.loc[frame["market_code"] == market].copy()
        train = frame.loc[frame["market_code"] != market]
        if len(train) < 3 or test.empty:
            raise RuntimeError(f"Not enough rows to hold out {market}")
        model = _fit(train, features, SEED, target)
        test["pred_loocv"] = _predict(model, test, features)
        test["baseline_loocv"] = float(train[target].mean())
        parts.append(test)
    return pd.concat(parts, axis=0)


def _completeness(frame: pd.DataFrame, fields: list[str]) -> pd.Series:
    return frame[fields].notna().sum(axis=1) / len(fields)


def train() -> int:
    configure_logging()
    np.random.seed(SEED)
    if not FEATURE_MATRIX_PATH.exists():
        logger.error("Missing %s. Run: python -m src.features.build", FEATURE_MATRIX_PATH)
        return 1
    frame = pd.read_csv(FEATURE_MATRIX_PATH)
    frame = frame.reset_index(drop=True)
    channel_ready = frame[frame[TARGET_COLUMN].notna()].copy()
    channel_markets = int(channel_ready["market_code"].nunique()) if not channel_ready.empty else 0
    market_ready = (
        frame[frame[OPPORTUNITY_COLUMN].notna()]
        .sort_values(["market_code", "channel"])
        .groupby("market_code", as_index=False)
        .head(1)
        .copy()
    )
    if channel_markets >= 4:
        label_mode = "channel_proxy"
        labeled = channel_ready
        features = MODEL_FEATURES
        target = TARGET_COLUMN
        comp_fields = list(COMPLETENESS_FIELDS)
        channel_informed = True
    elif len(market_ready) >= 4:
        label_mode = "market_opportunity"
        labeled = market_ready
        features = MARKET_MODEL_FEATURES
        target = OPPORTUNITY_COLUMN
        comp_fields = [
            field
            for field in COMPLETENESS_FIELDS
            if field not in {"channel_attention_share", "channel_pageview_growth"}
        ]
        channel_informed = False
        logger.warning(
            "Channel attention is too sparse (%s markets). Training on the market opportunity index only.",
            channel_markets,
        )
    else:
        logger.error("Not enough labeled markets to train. Refusing to invent rows.")
        return 1

    missing = [name for name in features if name not in labeled.columns]
    if missing:
        logger.error("Feature matrix is missing columns: %s", ", ".join(missing))
        return 1
    usable = [name for name in features if labeled[name].notna().any()]
    dropped = [name for name in features if name not in usable]
    if dropped:
        logger.warning("Dropping model features that are null on every labeled row: %s", ", ".join(dropped))
    if len(usable) < 2:
        logger.error("Fewer than two usable features. Not training on an empty design matrix.")
        return 1
    features = tuple(usable)

    logger.info("training mode=%s rows=%s features=%s", label_mode, len(labeled), len(features))
    loocv = _loocv(labeled, features, target)
    y_true = loocv[target].to_numpy(dtype=float)
    y_pred = loocv["pred_loocv"].to_numpy(dtype=float)
    y_base = loocv["baseline_loocv"].to_numpy(dtype=float)
    loocv_metrics = _metrics(y_true, y_pred)
    baseline_metrics = _metrics(y_true, y_base)
    models = [_fit(labeled, features, SEED + offset, target) for offset in range(ENSEMBLE_SIZE)]
    full_matrix = np.vstack([_predict(model, labeled, features) for model in models])
    full_mean = full_matrix.mean(axis=0)
    full_std = full_matrix.std(axis=0)
    insample = _metrics(labeled[target].to_numpy(dtype=float), full_mean)

    mae = float(loocv_metrics["mae"] or 0.0)
    rmse = float(loocv_metrics["rmse"] or 0.0)
    separation = separation_ratio(y_pred.tolist(), y_true.tolist())
    loocv = loocv.copy()
    loocv["feature_completeness"] = _completeness(loocv, comp_fields)
    loocv["abs_err_loocv"] = (loocv[target] - loocv["pred_loocv"]).abs()
    loocv["confidence"] = [
        confidence_score(
            float(comp),
            separation,
            error_penalty(float(err), mae, rmse),
        )
        for comp, err in zip(loocv["feature_completeness"], loocv["abs_err_loocv"])
    ]
    if not channel_informed:
        loocv["confidence"] = [min(0.85, value * 0.5) for value in loocv["confidence"]]

    labeled_keys = list(zip(labeled["market_code"].tolist(), labeled["channel"].tolist()))
    mean_by_key = {key: float(value) for key, value in zip(labeled_keys, full_mean.tolist())}
    std_by_key = {key: float(value) for key, value in zip(labeled_keys, full_std.tolist())}
    if not channel_informed:
        expanded_mean = {}
        expanded_std = {}
        for (market, _channel), value in mean_by_key.items():
            for channel in frame["channel"].drop_duplicates().tolist():
                expanded_mean[(market, channel)] = value
                expanded_std[(market, channel)] = std_by_key[(market, _channel)]
        mean_by_key = expanded_mean
        std_by_key = expanded_std

    loocv_by_market_channel = {
        (row.market_code, row.channel): row for row in loocv.itertuples(index=False)
    }
    loocv_channel_for_market = {
        market: rows.iloc[0] for market, rows in loocv.groupby("market_code")["channel"]
    }
    prediction_rows: list[dict] = []
    omitted: list[dict] = []
    seen_omitted: set[str] = set()
    for row in frame.itertuples(index=False):
        if channel_informed:
            loocv_row = loocv_by_market_channel.get((row.market_code, row.channel))
            if loocv_row is None:
                if row.market_code not in seen_omitted:
                    seen_omitted.add(row.market_code)
                    omitted.append(
                        {
                            "market_code": row.market_code,
                            "reason": (
                                "No proxy label. Channel attention share was missing, "
                                "so the row was not trained or allocated."
                            ),
                        }
                    )
                continue
        else:
            anchor = loocv_channel_for_market.get(row.market_code)
            loocv_row = loocv_by_market_channel.get((row.market_code, anchor)) if anchor is not None else None
            if loocv_row is None:
                continue
        prediction_rows.append(
            {
                "market_code": row.market_code,
                "market_name": row.market_name,
                "channel": row.channel,
                "channel_label": row.channel_label,
                "allocation_group": (
                    f"{row.market_code}:{row.channel}" if channel_informed else str(row.market_code)
                ),
                "label_mode": label_mode,
                "channel_informed": int(channel_informed),
                "y_true": float(getattr(loocv_row, target)),
                "pred_loocv": float(loocv_row.pred_loocv),
                "pred_full": float(mean_by_key[(row.market_code, row.channel)]),
                "pred_full_std": float(std_by_key[(row.market_code, row.channel)]),
                "feature_completeness": float(loocv_row.feature_completeness),
                "confidence": float(loocv_row.confidence),
            }
        )

    if not prediction_rows:
        logger.error("Leave-one-market-out produced no rows.")
        return 1

    predictions = pd.DataFrame(prediction_rows)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(PREDICTIONS_PATH, index=False)
    artifact = {
        "models": models,
        "model_features": list(features),
        "label_mode": label_mode,
        "target": target,
        "formula_id": "proxy-v1",
        "seed": SEED,
        "ensemble_size": ENSEMBLE_SIZE,
    }
    joblib.dump(artifact, MODEL_PATH)
    importances = _importances(models, features)
    manifest_run = None
    if MANIFEST_PATH.exists():
        manifest_run = read_json(MANIFEST_PATH).get("run_id")
    metrics = {
        "generated_at": iso_now(),
        "ingestion_run_id": manifest_run,
        "label_mode": label_mode,
        "channel_informed": channel_informed,
        "target": target,
        "estimator": "xgboost.XGBRegressor",
        "why_xgboost": WHY_XGBOOST,
        "hyperparameters": {**XGB_PARAMS, "random_state_base": SEED, "ensemble_size": ENSEMBLE_SIZE},
        "validation": "leave_one_market_out",
        "loocv": loocv_metrics,
        "loocv_mean_baseline": baseline_metrics,
        "insample_full_fit": insample,
        "separation": separation,
        "feature_importances_gain": importances,
        "omitted_markets": omitted,
        "confidence_cap": 0.85,
        "formula_inputs_also_in_model": list(FORMULA_AND_MODEL),
        "limitations": list(LIMITATIONS),
    }
    write_json(METRICS_PATH, metrics)
    write_json(
        METADATA_PATH,
        {
            "generated_at": metrics["generated_at"],
            "model_path": MODEL_PATH.name,
            "formula_id": "proxy-v1",
            "formula": FORMULA_TEXT,
            "why_xgboost": WHY_XGBOOST,
            "label_mode": label_mode,
            "model_features": list(features),
            "libraries": {
                "xgboost": version("xgboost"),
                "scikit-learn": version("scikit-learn"),
                "pandas": version("pandas"),
                "numpy": version("numpy"),
            },
            "metrics": metrics,
            "limitations": list(LIMITATIONS),
        },
    )
    logger.info(
        "LOOCV MAE %.4f RMSE %.4f R2 %s | baseline MAE %.4f | saved %s",
        loocv_metrics["mae"],
        loocv_metrics["rmse"],
        "n/a" if loocv_metrics["r2"] is None else f"{loocv_metrics['r2']:.3f}",
        baseline_metrics["mae"],
        MODEL_PATH.name,
    )
    return 0


def main() -> int:
    return train()


if __name__ == "__main__":
    raise SystemExit(main())
