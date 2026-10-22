"""Turn a World Bank envelope into one macro record per market."""

from __future__ import annotations

from src.config import MARKETS
from src.features.series import cagr_from_year_map, internet_user_series, latest_positive, year_map
from src.ingestion.worldbank import rows_from_body, series_by_iso3

LATEST_FIELDS: dict[str, tuple[str, str]] = {
    "NY.GDP.PCAP.CD": ("gdp_per_capita_usd", "gdp_per_capita_year"),
    "NY.GDP.PCAP.PP.CD": ("gdp_per_capita_ppp_usd", "gdp_per_capita_ppp_year"),
    "NY.GDP.MKTP.CD": ("gdp_current_usd", "gdp_current_usd_year"),
    "IT.CEL.SETS.P2": ("mobile_per_100", "mobile_per_100_year"),
    "IT.NET.BBND.P2": ("broadband_per_100", "broadband_per_100_year"),
    "SP.URB.TOTL.IN.ZS": ("urban_pct", "urban_pct_year"),
    "SP.POP.0014.TO.ZS": ("share_age_0_14", "share_age_0_14_year"),
    "SP.POP.1564.TO.ZS": ("share_age_15_64", "share_age_15_64_year"),
    "FP.CPI.TOTL.ZG": ("inflation_pct", "inflation_pct_year"),
    "PA.NUS.FCRF": ("fx_lcu_per_usd", "fx_lcu_per_usd_year"),
    "IT.NET.SECR.P6": ("secure_servers_per_million", "secure_servers_per_million_year"),
}


def indicator_maps(envelope: dict, indicator: str) -> dict[str, dict[int, float]]:
    block = (envelope.get("indicators") or {}).get(indicator) or {}
    empty = {market.iso3: {} for market in MARKETS}
    if not block.get("ok"):
        return empty
    series = series_by_iso3(rows_from_body(block.get("body")))
    return {iso: year_map(points) for iso, points in series.items()}


def _latest_allow_negative(values: dict[int, float]) -> tuple[int | None, float | None]:
    """Inflation can be negative, so the usual positive filter does not apply."""
    if not values:
        return None, None
    year, value = max(values.items())
    return year, value


def market_macro_rows(envelope: dict) -> dict[str, dict]:
    population = indicator_maps(envelope, "SP.POP.TOTL")
    internet_pct = indicator_maps(envelope, "IT.NET.USER.ZS")
    latest_maps = {indicator: indicator_maps(envelope, indicator) for indicator in LATEST_FIELDS}
    rows: dict[str, dict] = {}
    for market in MARKETS:
        row: dict = {"market_code": market.code, "market_name": market.name}
        pop_year, pop_value = latest_positive(population[market.iso3])
        row["population"] = pop_value
        row["population_year"] = pop_year
        pct_year, pct_value = latest_positive(internet_pct[market.iso3])
        row["internet_pct"] = pct_value
        row["internet_pct_year"] = pct_year
        users = internet_user_series(population[market.iso3], internet_pct[market.iso3])
        users_year, users_value = latest_positive(users)
        cagr, cagr_start, cagr_end = cagr_from_year_map(users)
        row["internet_users"] = users_value
        row["internet_users_year"] = users_year
        row["internet_user_cagr"] = cagr
        row["internet_user_cagr_start_year"] = cagr_start
        row["internet_user_cagr_end_year"] = cagr_end
        for indicator, (value_key, year_key) in LATEST_FIELDS.items():
            series = latest_maps[indicator][market.iso3]
            if indicator == "FP.CPI.TOTL.ZG":
                year, value = _latest_allow_negative(series)
            else:
                year, value = latest_positive(series)
            row[value_key] = value
            row[year_key] = year
        rows[market.code] = row
    return rows
