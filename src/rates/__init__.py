"""Optional CPM/CPC rate-card hooks.

Rates are loaded only when a configured JSON file is present and enabled.
Without credentials or a file, every rate stays null — nothing is invented.
See ``src.rates.rate_card`` for the JSON shape and env vars.
"""

from src.rates.rate_card import RateCard, RateLookup, load_rate_card, rates_for
from src.rates.cost_adjust import cost_efficiency_factors

__all__ = [
    "RateCard",
    "RateLookup",
    "load_rate_card",
    "rates_for",
    "cost_efficiency_factors",
]
