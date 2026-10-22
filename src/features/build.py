"""Build the market × channel matrix from the latest raw manifest."""

from __future__ import annotations

import logging

import pandas as pd

from src.config import (
    CHANNEL_LABELS,
    CHANNELS,
    FEATURE_DICTIONARY_PATH,
    FEATURE_MATRIX_PATH,
    MANIFEST_PATH,
    MARKET_COMPONENTS_PATH,
    PROCESSED_DIR,
    PROXY_NOTES_PATH,
    ROOT,
    configure_logging,
)
from src.features.apple_math import apple_chart_features
from src.features.dictionary import COLUMNS, column_names
from src.features.indie import indie_scores
from src.features.macro import market_macro_rows
from src.features.pageviews import channel_attention
from src.features.proxy_target import FORMULA_TEXT, build_opportunity, proxy_return
from src.jsonutil import read_json, write_json
from src.model.spec import COMPLETENESS_FIELDS, FORMULA_ID

logger = logging.getLogger(__name__)


def _load(relative: str | None) -> dict | None:
    if not relative:
        return None
    path = ROOT / relative
    if not path.exists():
        logger.warning("missing raw file %s", relative)
        return None
    return read_json(path)


def build() -> int:
    configure_logging()
    if not MANIFEST_PATH.exists():
        logger.error("No manifest at %s. Run: python -m src.ingestion.run", MANIFEST_PATH)
        return 1
    manifest = read_json(MANIFEST_PATH)
    files = manifest.get("files") or {}
    macro = market_macro_rows(_load(files.get("worldbank")) or {"indicators": {}})
    fx = _load(files.get("frankfurter")) or {}
    apple = _load(files.get("apple_charts")) or {}
    attention = channel_attention(_load(files.get("attention")))
    fx_date = fx.get("date")
    fx_by_market = fx.get("by_market") or {}

    users = {code: row.get("internet_users") for code, row in macro.items()}
    cagr = {code: row.get("internet_user_cagr") for code, row in macro.items()}
    age = {code: row.get("share_age_0_14") for code, row in macro.items()}
    gdp = {code: row.get("gdp_per_capita_usd") for code, row in macro.items()}
    opportunity = build_opportunity(users, cagr, age, gdp)
    diversity = {
        code: attention[code]["streaming_platform_diversity"] for code in macro
    }
    indie = indie_scores(
        {code: row.get("internet_pct") for code, row in macro.items()},
        {code: row.get("mobile_per_100") for code, row in macro.items()},
        {code: row.get("broadband_per_100") for code, row in macro.items()},
        age,
        gdp,
        diversity,
    )
    eligible = sum(1 for score in opportunity.scores.values() if score is not None)
    if eligible < 4:
        logger.error(
            "Opportunity scores exist for %s markets. Need 4. Not inventing labels.",
            eligible,
        )
        return 1

    matrix_rows: list[dict] = []
    component_rows: list[dict] = []
    for code, base in macro.items():
        market_attention = attention[code]
        component = {
            "market_code": code,
            "market_name": base["market_name"],
            "internet_users": base.get("internet_users"),
            "internet_users_year": base.get("internet_users_year"),
            "internet_user_cagr": base.get("internet_user_cagr"),
            "share_age_0_14": base.get("share_age_0_14"),
            "gdp_per_capita_usd": base.get("gdp_per_capita_usd"),
            "opportunity_score": opportunity.scores.get(code),
            "indie_accessibility_score": indie.scores.get(code),
            "streaming_platform_diversity": market_attention["streaming_platform_diversity"],
            **{
                f"component_{name}": value
                for name, value in (opportunity.components.get(code) or {}).items()
            },
        }
        component_rows.append(component)
        for channel in CHANNELS:
            row = dict(base)
            row["channel"] = channel
            row["channel_label"] = CHANNEL_LABELS[channel]
            row["fx_frankfurter_lcu_per_usd"] = fx_by_market.get(code)
            row["fx_frankfurter_date"] = fx_date
            chart = (apple.get("charts") or {}).get(code) or {}
            row.update(apple_chart_features(chart.get("body") if chart.get("ok") else None))
            row["pageview_window_start"] = market_attention["pageview_window_start"]
            row["pageview_window_end"] = market_attention["pageview_window_end"]
            row.update(market_attention["channels"][channel])
            row["streaming_pageview_growth"] = market_attention["streaming_pageview_growth"]
            row["short_video_pageview_growth"] = market_attention["short_video_pageview_growth"]
            row["social_pageview_growth"] = market_attention["social_pageview_growth"]
            row["streaming_platform_hhi"] = market_attention["streaming_platform_hhi"]
            row["streaming_platform_diversity"] = market_attention["streaming_platform_diversity"]
            row["indie_accessibility_score"] = indie.scores.get(code)
            row["opportunity_score"] = opportunity.scores.get(code)
            row["proxy_return_per_dollar"] = proxy_return(
                opportunity.scores.get(code),
                row.get("channel_attention_share"),
            )
            row["channel_is_streaming_dsp"] = 1 if channel == "streaming_dsp" else 0
            row["channel_is_short_video"] = 1 if channel == "short_video" else 0
            row["channel_is_social_influencer"] = 1 if channel == "social_influencer" else 0
            matrix_rows.append(row)

    frame = pd.DataFrame(matrix_rows)
    for name in column_names():
        if name not in frame.columns:
            frame[name] = pd.NA
    frame = frame[column_names()]
    frame["feature_completeness"] = (
        frame[list(COMPLETENESS_FIELDS)].notna().sum(axis=1) / len(COMPLETENESS_FIELDS)
    )
    year_columns = [name for name in frame.columns if name.endswith("_year")]
    for name in year_columns:
        frame[name] = pd.to_numeric(frame[name], errors="coerce").astype("Int64")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(FEATURE_MATRIX_PATH, index=False)
    pd.DataFrame(component_rows).to_csv(MARKET_COMPONENTS_PATH, index=False)
    write_json(FEATURE_DICTIONARY_PATH, {"columns": list(COLUMNS)})
    labeled = int(frame["proxy_return_per_dollar"].notna().sum())
    write_json(
        PROXY_NOTES_PATH,
        {
            "formula_id": FORMULA_ID,
            "formula": FORMULA_TEXT,
            "active_weights": opportunity.active_weights,
            "eligible_markets": opportunity.eligible,
            "opportunity_notes": opportunity.notes,
            "indie_active_weights": indie.active_weights,
            "indie_notes": indie.notes,
            "labeled_rows": labeled,
            "markets": len(macro),
            "ingestion_run_id": manifest.get("run_id"),
            "limitation": (
                "proxy_return_per_dollar is not observed campaign ROI. "
                "Unavailable sync, MAU, brand-deal, and CPM columns are null on purpose."
            ),
        },
    )
    logger.info("wrote %s (%s labeled rows)", FEATURE_MATRIX_PATH, labeled)
    return 0


def main() -> int:
    return build()


if __name__ == "__main__":
    raise SystemExit(main())
