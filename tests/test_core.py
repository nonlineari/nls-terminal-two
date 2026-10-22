"""Unit tests for the proxy label, allocation, and the model contract.

These tests do not touch the network and do not need a trained model.
"""

from __future__ import annotations

import math
import unittest

from src.features.apple_math import apple_chart_features
from src.features.attention_math import attention_shares, hhi
from src.features.dictionary import column_names
from src.features.indie import INDIE_WEIGHTS, indie_scores
from src.features.pageviews import _previous_ym
from src.features.proxy_target import (
    ATTENTION_FLOOR,
    ATTENTION_WEIGHT,
    OPPORTUNITY_WEIGHTS,
    build_opportunity,
    proxy_return,
)
from src.features.series import cagr_from_year_map, internet_user_series, minmax_dict
from src.model.spec import (
    COMPLETENESS_FIELDS,
    FORMULA_AND_MODEL,
    LEAKAGE_COLUMNS,
    MODEL_FEATURES,
    UNAVAILABLE_COLUMNS,
)
from src.output.scoring import (
    CONFIDENCE_CAP,
    allocate_groups,
    confidence_score,
    money_split,
    percent_split,
)


class SeriesTests(unittest.TestCase):
    def test_cagr_doubles_over_five_years(self) -> None:
        cagr, start, end = cagr_from_year_map({2015: 100.0, 2018: 150.0, 2020: 200.0})
        self.assertEqual(start, 2015)
        self.assertEqual(end, 2020)
        self.assertAlmostEqual(cagr, 2 ** (1 / 5) - 1, places=6)

    def test_cagr_rejects_short_span(self) -> None:
        cagr, _, _ = cagr_from_year_map({2020: 100.0, 2022: 200.0}, min_span=3)
        self.assertIsNone(cagr)

    def test_internet_users_use_shared_years_only(self) -> None:
        users = internet_user_series({2020: 1000.0, 2021: 1100.0}, {2021: 50.0})
        self.assertEqual(users, {2021: 550.0})

    def test_minmax_constant_is_half(self) -> None:
        self.assertEqual(minmax_dict({"a": 3.0, "b": 3.0}), {"a": 0.5, "b": 0.5})


class ProxyTests(unittest.TestCase):
    def test_weights_sum_to_one(self) -> None:
        self.assertAlmostEqual(sum(OPPORTUNITY_WEIGHTS.values()), 1.0)
        self.assertAlmostEqual(ATTENTION_FLOOR + ATTENTION_WEIGHT, 1.0)
        self.assertAlmostEqual(sum(INDIE_WEIGHTS.values()), 1.0)

    def test_larger_reach_and_lower_cost_ranks_higher(self) -> None:
        result = build_opportunity(
            internet_users={"A": 1e8, "B": 1e7},
            internet_user_cagr={"A": 0.10, "B": 0.01},
            share_age_0_14={"A": 25.0, "B": 10.0},
            gdp_per_capita={"A": 5000.0, "B": 50000.0},
        )
        self.assertGreater(result.scores["A"], result.scores["B"])
        self.assertAlmostEqual(sum(result.active_weights.values()), 1.0)

    def test_missing_cagr_is_dropped_not_invented(self) -> None:
        result = build_opportunity(
            internet_users={"A": 1e8, "B": 1e7},
            internet_user_cagr={"A": 0.1, "B": None},
            share_age_0_14={"A": 20.0, "B": 20.0},
            gdp_per_capita={"A": 10000.0, "B": 20000.0},
        )
        self.assertNotIn("momentum", result.active_weights)
        self.assertTrue(any("momentum" in note for note in result.notes))

    def test_attention_scales_return_and_missing_share_is_unlabeled(self) -> None:
        low = proxy_return(0.5, 0.0)
        high = proxy_return(0.5, 1.0)
        self.assertGreater(high, low)
        self.assertIsNone(proxy_return(0.5, None))
        self.assertIsNone(proxy_return(None, 0.5))


class AttentionTests(unittest.TestCase):
    def test_shares_sum_to_one(self) -> None:
        shares = attention_shares({"a": 20.0, "b": 30.0, "c": 50.0})
        self.assertAlmostEqual(sum(shares.values()), 1.0)

    def test_missing_channel_does_not_renormalize(self) -> None:
        shares = attention_shares({"a": 10.0, "b": None, "c": 10.0})
        self.assertEqual(list(shares.values()), [None, None, None])

    def test_hhi_of_equal_pair(self) -> None:
        self.assertAlmostEqual(hhi([10.0, 10.0]), 0.5)

    def test_previous_month_crosses_january(self) -> None:
        self.assertEqual(_previous_ym(202501), 202412)


class IndieTests(unittest.TestCase):
    def test_scores_stay_in_unit_interval_and_prefer_open_markets(self) -> None:
        result = indie_scores(
            internet_pct={"A": 90.0, "B": 40.0},
            mobile_per_100={"A": 100.0, "B": 80.0},
            broadband_per_100={"A": 40.0, "B": 10.0},
            share_age_0_14={"A": 20.0, "B": 10.0},
            gdp_per_capita={"A": 10000.0, "B": 50000.0},
            platform_diversity={"A": 0.8, "B": 0.2},
        )
        self.assertGreater(result.scores["A"], result.scores["B"])
        for score in result.scores.values():
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)

    def test_mobile_cap_stops_multi_sim_from_owning_the_scale(self) -> None:
        capped = indie_scores(
            internet_pct={"A": 50.0, "B": 50.0},
            mobile_per_100={"A": 150.0, "B": 400.0},
            broadband_per_100={"A": 20.0, "B": 20.0},
            share_age_0_14={"A": 15.0, "B": 15.0},
            gdp_per_capita={"A": 20000.0, "B": 20000.0},
            platform_diversity={"A": 0.5, "B": 0.5},
        )
        self.assertAlmostEqual(capped.scores["A"], capped.scores["B"])


class ContractTests(unittest.TestCase):
    def test_model_features_do_not_include_proxy_inputs(self) -> None:
        self.assertFalse(set(MODEL_FEATURES) & set(LEAKAGE_COLUMNS))
        self.assertTrue(set(FORMULA_AND_MODEL).issubset(MODEL_FEATURES))
        self.assertFalse(set(FORMULA_AND_MODEL) & set(LEAKAGE_COLUMNS))
        self.assertTrue(set(COMPLETENESS_FIELDS).issubset(MODEL_FEATURES))
        self.assertFalse(set(UNAVAILABLE_COLUMNS) & set(MODEL_FEATURES))
        names = set(column_names())
        self.assertTrue(set(MODEL_FEATURES).issubset(names))
        self.assertTrue(set(LEAKAGE_COLUMNS).issubset(names))
        self.assertTrue(set(UNAVAILABLE_COLUMNS).issubset(names))
        self.assertNotIn("market_code", MODEL_FEATURES)

    def test_apple_skips_generic_music_genre(self) -> None:
        features = apple_chart_features(
            {
                "feed": {
                    "updated": "2026-10-01T00:00:00Z",
                    "results": [
                        {
                            "artistName": "Artist",
                            "releaseDate": "2026-09-01",
                            "genres": [
                                {"name": "Music"},
                                {"name": "Pop"},
                            ],
                        }
                    ],
                }
            }
        )
        self.assertEqual(features["apple_genre_hhi"], 1.0)
        self.assertEqual(features["apple_chart_tracks"], 1)
        self.assertEqual(features["apple_share_new_90d"], 1.0)
        rfc = apple_chart_features(
            {
                "feed": {
                    "updated": "Thu, 22 Oct 2026 05:46:59 +0000",
                    "results": [
                        {
                            "artistName": "Artist",
                            "releaseDate": "2026-10-13",
                            "genres": [{"name": "K-Pop"}],
                        }
                    ],
                }
            }
        )
        self.assertEqual(rfc["apple_chart_as_of"], "2026-10-22")
        self.assertEqual(rfc["apple_share_new_90d"], 1.0)


class AllocationTests(unittest.TestCase):
    def test_percent_and_money_sum(self) -> None:
        percents = percent_split([1, 1, 1])
        self.assertAlmostEqual(sum(percents), 100.0)
        amounts = money_split(100000, percents)
        self.assertEqual(round(sum(amounts) * 100), 10_000_000)

    def test_channel_groups_sum_to_budget(self) -> None:
        groups = [
            [{"market_name": "Korea", "channel": "a", "pred": 0.4, "confidence": 0.5}],
            [{"market_name": "Japan", "channel": "b", "pred": 0.2, "confidence": 0.5}],
            [{"market_name": "Indonesia", "channel": "c", "pred": 0.8, "confidence": 0.4}],
        ]
        rows = allocate_groups(groups, 100000)
        self.assertAlmostEqual(sum(row["percent"] for row in rows), 100.0)
        self.assertEqual(round(sum(row["amount"] for row in rows) * 100), 10_000_000)

    def test_shared_group_is_not_triple_counted(self) -> None:
        groups = [
            [
                {"pred": 1.0, "confidence": 1.0, "channel": "a"},
                {"pred": 1.0, "confidence": 1.0, "channel": "b"},
                {"pred": 1.0, "confidence": 1.0, "channel": "c"},
            ]
        ]
        rows = allocate_groups(groups, 90)
        self.assertEqual(len(rows), 3)
        self.assertAlmostEqual(sum(row["amount"] for row in rows), 90.0)
        self.assertTrue(all(math.isclose(row["amount"], 30.0) for row in rows))

    def test_non_positive_predictions_fall_back_to_equal_weights(self) -> None:
        groups = [
            [{"pred": -1.0, "confidence": 0.4}],
            [{"pred": 0.0, "confidence": 0.9}],
        ]
        rows = allocate_groups(groups, 50)
        self.assertAlmostEqual(rows[0]["percent"], rows[1]["percent"])
        self.assertAlmostEqual(sum(row["percent"] for row in rows), 100.0)

    def test_confidence_never_exceeds_cap(self) -> None:
        self.assertLessEqual(confidence_score(1, 1, 1), CONFIDENCE_CAP)
        self.assertLessEqual(confidence_score(5, 5, 5), CONFIDENCE_CAP)
        self.assertGreaterEqual(confidence_score(0, 0, 0), 0.05)


if __name__ == "__main__":
    unittest.main()
