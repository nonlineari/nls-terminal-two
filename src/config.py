"""Paths, markets, and run constants shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
MODELS_DIR = ROOT / "models"

MANIFEST_PATH = RAW_DIR / "manifest.json"
LATEST_RUN_PATH = RAW_DIR / "latest_run.json"
FAILURES_PATH = RAW_DIR / "_failed_sources.jsonl"

FEATURE_MATRIX_PATH = PROCESSED_DIR / "feature_matrix.csv"
MARKET_COMPONENTS_PATH = PROCESSED_DIR / "market_components.csv"
FEATURE_DICTIONARY_PATH = PROCESSED_DIR / "feature_dictionary.json"
PROXY_NOTES_PATH = PROCESSED_DIR / "proxy_target.json"

MODEL_PATH = MODELS_DIR / "promo_return_xgb.joblib"
METADATA_PATH = MODELS_DIR / "metadata.json"
METRICS_PATH = MODELS_DIR / "metrics.json"
PREDICTIONS_PATH = MODELS_DIR / "loocv_predictions.csv"

SEED = 42
FORMULA_ID = "proxy-v1"
USER_AGENT = (
    "NLSTerminalTwo/0.1 (local music-market research; bot=false; "
    "public-data cache for reproducible promo-budget prototype)"
)

# Pageview growth below this prior-window total is treated as missing.
# Tiny Wikipedia bases produce ratios that are not attention trends.
MIN_PRIOR_PAGEVIEWS = 50
# A window must contain at least this many monthly observations.
MIN_PAGEVIEW_MONTHS = 8
# Indie-score mobile input saturates here. Hong Kong's SIM-per-person
# figure is far above 150 and is not extra promotional access.
MOBILE_SATURATION_PER_100 = 150.0


@dataclass(frozen=True)
class Market:
    code: str
    iso3: str
    name: str
    apple_store: str
    wiki_site: str
    wiki_project: str
    currency: str


MARKETS: tuple[Market, ...] = (
    Market("KR", "KOR", "Korea", "kr", "kowiki", "ko.wikipedia", "KRW"),
    Market("JP", "JPN", "Japan", "jp", "jawiki", "ja.wikipedia", "JPY"),
    Market("ID", "IDN", "Indonesia", "id", "idwiki", "id.wikipedia", "IDR"),
    Market("VN", "VNM", "Vietnam", "vn", "viwiki", "vi.wikipedia", "VND"),
    Market("TH", "THA", "Thailand", "th", "thwiki", "th.wikipedia", "THB"),
    Market("CN", "CHN", "China", "cn", "zhwiki", "zh.wikipedia", "CNY"),
    Market("HK", "HKG", "Hong Kong", "hk", "zh_yuewiki", "zh-yue.wikipedia", "HKD"),
)

# Channels that can receive a score when a public attention proxy exists.
CHANNELS: tuple[str, ...] = (
    "streaming_dsp",
    "short_video",
    "social_influencer",
)

CHANNEL_LABELS: dict[str, str] = {
    "streaming_dsp": "Streaming DSP",
    "short_video": "Short video",
    "social_influencer": "Social / influencer",
}

# Requested themes with no public numeric series in this pipeline.
UNSCORED_CHANNELS: dict[str, str] = {
    "sync_licensing": (
        "No public sync or licensing rate card by placement type "
        "(film, TV, advertising, games) was retrieved."
    ),
    "paid_social": (
        "No public CPM or CPC series by platform and territory was retrieved."
    ),
}

ISO_PATH = ";".join(market.iso3 for market in MARKETS)
MARKET_BY_CODE = {market.code: market for market in MARKETS}
MARKET_BY_ISO3 = {market.iso3: market for market in MARKETS}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_run_id() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%SZ")


def configure_logging() -> None:
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        force=True,
    )
