"""Aggregate cached Wikimedia pageview series to market × channel."""

from __future__ import annotations

from src.config import CHANNELS, MIN_PAGEVIEW_MONTHS, MIN_PRIOR_PAGEVIEWS
from src.features.attention_math import attention_shares, diversity_from_hhi, hhi, pageview_growth


def _ym(timestamp: str) -> int | None:
    if not isinstance(timestamp, str) or len(timestamp) < 6 or not timestamp[:6].isdigit():
        return None
    return int(timestamp[:6])


def _window_sum(items: list[dict], start_ym: int, end_ym: int) -> tuple[float | None, int]:
    months: list[float] = []
    for item in items:
        ym = _ym(str(item.get("timestamp", "")))
        if ym is None or ym < start_ym or ym > end_ym:
            continue
        views = item.get("views")
        if views is None:
            continue
        months.append(float(views))
    if len(months) < MIN_PAGEVIEW_MONTHS:
        return None, len(months)
    return float(sum(months)), len(months)


def _ym_label(value: int) -> str:
    return f"{value // 100:04d}-{value % 100:02d}"


def _previous_ym(ym: int) -> int:
    year, month = divmod(ym, 100)
    if month == 1:
        return (year - 1) * 100 + 12
    return year * 100 + (month - 1)


def channel_attention(envelope: dict | None) -> dict[str, dict]:
    """Return market_code -> channel stats, plus market-level streaming diversity.

    The returned dict is keyed by market code. Each value has `channels`,
    `streaming_platform_hhi`, `streaming_platform_diversity`, and window labels.
    """
    from src.config import MARKETS

    window = (envelope or {}).get("window") or {}
    start_ym = int(window["prior_start_ym"]) if window.get("prior_start_ym") else None
    mid_ym = int(window["last_start_ym"]) if window.get("last_start_ym") else None
    end_ym = int(window["end_ym"]) if window.get("end_ym") else None
    empty_channels = {
        channel: {
            "channel_pageviews_12m": None,
            "channel_pageviews_prior_12m": None,
            "channel_pageview_growth": None,
            "channel_attention_share": None,
            "channel_platforms_resolved": 0,
            "channel_platforms_with_views": 0,
        }
        for channel in CHANNELS
    }
    out: dict[str, dict] = {}
    for market in MARKETS:
        out[market.code] = {
            "pageview_window_start": _ym_label(start_ym) if start_ym else None,
            "pageview_window_end": _ym_label(end_ym) if end_ym else None,
            "channels": {channel: dict(stats) for channel, stats in empty_channels.items()},
            "streaming_platform_hhi": None,
            "streaming_platform_diversity": None,
            "streaming_pageview_growth": None,
            "short_video_pageview_growth": None,
            "social_pageview_growth": None,
        }
    if start_ym is None or mid_ym is None or end_ym is None:
        return out

    # market -> channel -> list of last-12 platform totals
    streaming_levels: dict[str, list[float | None]] = {market.code: [] for market in MARKETS}
    for series in (envelope or {}).get("series") or []:
        market = series.get("market")
        channel = series.get("channel")
        if market not in out or channel not in CHANNELS:
            continue
        bucket = out[market]["channels"][channel]
        if series.get("title"):
            bucket["channel_platforms_resolved"] += 1
        if not series.get("ok"):
            continue
        last_sum, _ = _window_sum(series.get("items") or [], mid_ym, end_ym)
        prior_sum, _ = _window_sum(series.get("items") or [], start_ym, _previous_ym(mid_ym))
        if last_sum is None and prior_sum is None:
            continue
        bucket["channel_platforms_with_views"] += 1 if last_sum is not None else 0
        if channel == "streaming_dsp":
            streaming_levels[market].append(last_sum)
        if last_sum is not None:
            current = bucket["channel_pageviews_12m"]
            bucket["channel_pageviews_12m"] = (current or 0.0) + last_sum
        if prior_sum is not None:
            current = bucket["channel_pageviews_prior_12m"]
            bucket["channel_pageviews_prior_12m"] = (current or 0.0) + prior_sum

    for market in MARKETS:
        channels = out[market.code]["channels"]
        for channel in CHANNELS:
            stats = channels[channel]
            stats["channel_pageview_growth"] = pageview_growth(
                stats["channel_pageviews_12m"],
                stats["channel_pageviews_prior_12m"],
                MIN_PRIOR_PAGEVIEWS,
            )
        shares = attention_shares(
            {channel: channels[channel]["channel_pageviews_12m"] for channel in CHANNELS}
        )
        for channel in CHANNELS:
            channels[channel]["channel_attention_share"] = shares[channel]
        concentration = hhi(streaming_levels[market.code])
        out[market.code]["streaming_platform_hhi"] = concentration
        out[market.code]["streaming_platform_diversity"] = diversity_from_hhi(concentration)
        out[market.code]["streaming_pageview_growth"] = channels["streaming_dsp"]["channel_pageview_growth"]
        out[market.code]["short_video_pageview_growth"] = channels["short_video"]["channel_pageview_growth"]
        out[market.code]["social_pageview_growth"] = channels["social_influencer"]["channel_pageview_growth"]
    return out
