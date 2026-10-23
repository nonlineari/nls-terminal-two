"""Model contract: which columns may train, and which must not.

channel_attention_share is the exception that is both a formula input and a
model feature. It is the only observed channel-level signal. The cross-market
opportunity ingredients in LEAKAGE_COLUMNS stay out of the design matrix so a
high R² cannot be read as "the trees memorized the formula". They remain
correlated with mobile, broadband, and income-linked structure; that limit is
stated in the README and in metadata.
"""

from __future__ import annotations

MODEL_FEATURES: tuple[str, ...] = (
    "mobile_per_100",
    "broadband_per_100",
    "urban_pct",
    "inflation_pct",
    "secure_servers_per_million",
    "apple_genre_hhi",
    "apple_artist_diversity",
    "apple_share_new_90d",
    "channel_attention_share",
    "channel_pageview_growth",
    "channel_is_streaming_dsp",
    "channel_is_short_video",
    "channel_is_social_influencer",
)

# Used when no channel has an attention share. Target is then the market
# opportunity index, and the CLI splits each market equally across channels.
MARKET_MODEL_FEATURES: tuple[str, ...] = (
    "mobile_per_100",
    "broadband_per_100",
    "urban_pct",
    "inflation_pct",
    "secure_servers_per_million",
    "apple_genre_hhi",
    "apple_artist_diversity",
    "apple_share_new_90d",
)

COMPLETENESS_FIELDS: tuple[str, ...] = (
    "mobile_per_100",
    "broadband_per_100",
    "urban_pct",
    "inflation_pct",
    "secure_servers_per_million",
    "apple_genre_hhi",
    "apple_artist_diversity",
    "apple_share_new_90d",
    "channel_attention_share",
    "channel_pageview_growth",
)

LEAKAGE_COLUMNS: tuple[str, ...] = (
    "population",
    "internet_pct",
    "internet_users",
    "internet_user_cagr",
    "share_age_0_14",
    "share_age_15_64",
    "gdp_per_capita_usd",
    "gdp_per_capita_ppp_usd",
    "gdp_current_usd",
    "indie_accessibility_score",
    "opportunity_score",
    "proxy_return_per_dollar",
    "fx_lcu_per_usd",
    "fx_frankfurter_lcu_per_usd",
)

FORMULA_AND_MODEL: tuple[str, ...] = ("channel_attention_share",)

UNAVAILABLE_COLUMNS: tuple[str, ...] = (
    "streaming_mau_observed",
    "streaming_mau_growth_observed",
    "streaming_subscribers_observed",
    "sync_rate_film_usd",
    "sync_rate_tv_usd",
    "sync_rate_advertising_usd",
    "sync_rate_game_usd",
    "brand_deal_count_observed",
    "brand_deal_avg_usd_observed",
)

# Optional rate-card columns. Populated only when an enabled rate card is
# configured. Kept out of MODEL_FEATURES so training with nulls matches today;
# recommend/ uses them for cost-aware reweight when present.
OPTIONAL_RATE_COLUMNS: tuple[str, ...] = (
    "ad_cpm_usd_observed",
    "ad_cpc_usd_observed",
)

TARGET_COLUMN = "proxy_return_per_dollar"
OPPORTUNITY_COLUMN = "opportunity_score"

# Depth-wise trees with strong L2. Leaf-wise boosting (LightGBM's default)
# partitions tiny samples too eagerly; see the README for the choice.
XGB_PARAMS: dict[str, object] = {
    "n_estimators": 60,
    "max_depth": 2,
    "learning_rate": 0.05,
    "min_child_weight": 1,
    "subsample": 0.9,
    "colsample_bytree": 0.9,
    "reg_lambda": 8.0,
    "reg_alpha": 1.0,
    "gamma": 0.0,
    "objective": "reg:squarederror",
    "tree_method": "hist",
    "n_jobs": 1,
    "verbosity": 0,
}

ENSEMBLE_SIZE = 5

WHY_XGBOOST = (
    "XGBoost is the estimator because the training table is a few dozen rows. "
    "Depth-wise trees with max_depth 2 and a large L2 penalty stay shallower than "
    "LightGBM's leaf-wise default, which will isolate single markets on a sample "
    "this small. Either library would be underpowered; XGBoost is the more "
    "constrained default and installs as a single wheel. This is not a claim that "
    "gradient boosting recovers real promo ROI from public covariates."
)

LIMITATIONS: tuple[str, ...] = (
    "The training label is a documented formula, not NLS campaign profit or loss.",
    "Leave-one-market-out on seven markets is a small sample. The metrics move if one market is unusual.",
    "Language-edition Wikipedia pageviews are not streaming MAU and are not a clean country panel.",
    "No public sync rate card entered the model. Territory CPM/CPC enter the matrix only from an enabled local rate card; they are not model features.",
    "Ages 0-14 stand in for a youth audience. The 15-24 World Bank indicator id was rejected by the API.",
    "Mobile, broadband, and server density still correlate with income and internet use, so some fit is mechanical.",
    "Confidence is capped at 0.85 because the label is synthetic.",
    "Apple charts are one snapshot, not a growth series.",
    "Hong Kong mobile subscriptions per 100 people exceed 300 because of multi-SIM use. The indie score caps that input at 150.",
    "Output is a research allocation of a proxy index, not media-buying advice.",
)
