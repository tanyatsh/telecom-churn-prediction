"""Reconciliation and reproducibility checks for Phase 4A outputs."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from retention_scenarios import (  # noqa: E402
    DEFAULT_CONFIG,
    DEFAULT_DATABASE,
    DEFAULT_PHASE3A,
    build_outputs,
    contacted_count,
    sha256_file,
)


class RetentionScenarioChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.output_dir = PROJECT_ROOT / "outputs" / "powerbi" / "phase4a" / "v1"
        required = [
            "capacity_performance_v1.csv",
            "scenario_assumptions_v1.csv",
            "scenario_outcomes_v1.csv",
            "break_even_v1.csv",
            "sensitivity_analysis_v1.csv",
            "customer_targeting_v1.csv",
            "run_manifest_v1.json",
        ]
        missing = [name for name in required if not (cls.output_dir / name).is_file()]
        if missing:
            raise FileNotFoundError(f"Run src/retention_scenarios.py first; missing: {missing}")
        cls.capacity = pd.read_csv(cls.output_dir / "capacity_performance_v1.csv")
        cls.assumptions = pd.read_csv(cls.output_dir / "scenario_assumptions_v1.csv")
        cls.outcomes = pd.read_csv(cls.output_dir / "scenario_outcomes_v1.csv")
        cls.targeting = pd.read_csv(cls.output_dir / "customer_targeting_v1.csv")
        cls.manifest = json.loads(
            (cls.output_dir / "run_manifest_v1.json").read_text(encoding="utf-8")
        )

    def test_frozen_phase3a_artifacts_are_unchanged(self) -> None:
        for name, expected in self.manifest["source_phase3a_hashes"].items():
            with self.subTest(name=name):
                self.assertEqual(sha256_file(DEFAULT_PHASE3A / name), expected)
        self.assertFalse(self.manifest["individual_selection_uses_actual_churn"])

    def test_targeting_counts_nesting_and_ranking(self) -> None:
        self.assertEqual(len(self.targeting), 1_409)
        self.assertNotIn("actual_churn", self.targeting.columns)
        self.assertEqual(self.targeting["risk_rank"].tolist(), list(range(1, 1_410)))
        self.assertTrue(self.targeting["predicted_probability"].is_monotonic_decreasing)
        expected_counts = {10: 141, 20: 282, 30: 423}
        for percent, expected in expected_counts.items():
            self.assertEqual(int(self.targeting[f"selected_top_{percent}pct"].sum()), expected)
        self.assertTrue(
            (~self.targeting["selected_top_10pct"] | self.targeting["selected_top_20pct"]).all()
        )
        self.assertTrue(
            (~self.targeting["selected_top_20pct"] | self.targeting["selected_top_30pct"]).all()
        )

    def test_capacity_metrics_reconcile_to_frozen_labels(self) -> None:
        predictions = pd.read_csv(DEFAULT_PHASE3A / "test_predictions_v1.csv").sort_values(
            "risk_rank"
        )
        prevalence = predictions["actual_churn"].mean()
        for row in self.capacity.itertuples(index=False):
            count = contacted_count(len(predictions), row.capacity_fraction)
            churned = int(predictions.iloc[:count]["actual_churn"].sum())
            with self.subTest(capacity=row.capacity_fraction):
                self.assertEqual(row.contacted_customers, count)
                self.assertEqual(row.observed_churned_contacted, churned)
                self.assertAlmostEqual(row.observed_churn_capture, churned / 374, places=14)
                self.assertAlmostEqual(row.precision, churned / count, places=14)
                self.assertAlmostEqual(row.lift, (churned / count) / prevalence, places=14)

    def test_scenario_formulas_and_cost_incidence(self) -> None:
        for row in self.outcomes.itertuples(index=False):
            expected_cost = row.contacted_customers * (
                row.contact_cost_per_customer + row.offer_cost_per_customer
            )
            expected_gross = (
                row.probability_weighted_contribution_at_full_effect
                * row.relative_risk_reduction
            )
            with self.subTest(scenario=row.scenario, capacity=row.capacity_fraction):
                self.assertAlmostEqual(row.total_campaign_cost, expected_cost, places=10)
                self.assertAlmostEqual(
                    row.gross_expected_retained_contribution, expected_gross, places=8
                )
                self.assertAlmostEqual(
                    row.net_expected_scenario_value,
                    expected_gross - expected_cost,
                    places=8,
                )
                self.assertEqual(row.offer_cost_incidence, "every contacted customer")

    def test_assumptions_are_valid_and_explicitly_illustrative(self) -> None:
        self.assertTrue((self.assumptions["benefit_horizon_months"] > 0).all())
        self.assertTrue(self.assumptions["contribution_margin_rate"].between(0, 1).all())
        self.assertTrue(self.assumptions["relative_risk_reduction"].between(0, 1).all())
        self.assertTrue((self.assumptions["contact_cost_per_customer"] >= 0).all())
        self.assertTrue((self.assumptions["offer_cost_per_customer"] >= 0).all())
        self.assertTrue(
            self.assumptions["assumption_status"].str.contains("not empirically validated").all()
        )

    def test_saved_outputs_are_reproducible(self) -> None:
        recalculated, _ = build_outputs(DEFAULT_DATABASE, DEFAULT_PHASE3A, DEFAULT_CONFIG)
        saved_names = {
            "capacity_performance": "capacity_performance_v1.csv",
            "scenario_assumptions": "scenario_assumptions_v1.csv",
            "scenario_outcomes": "scenario_outcomes_v1.csv",
            "break_even": "break_even_v1.csv",
            "sensitivity_analysis": "sensitivity_analysis_v1.csv",
            "customer_targeting": "customer_targeting_v1.csv",
        }
        for name, filename in saved_names.items():
            saved = pd.read_csv(self.output_dir / filename)
            expected = recalculated[name]
            with self.subTest(table=name):
                self.assertEqual(list(saved.columns), list(expected.columns))
                self.assertEqual(saved.shape, expected.shape)
                for column in saved.columns:
                    if pd.api.types.is_numeric_dtype(expected[column]):
                        np.testing.assert_allclose(
                            saved[column].to_numpy(dtype=float),
                            expected[column].to_numpy(dtype=float),
                            rtol=1e-14,
                            atol=1e-10,
                        )
                    else:
                        self.assertEqual(
                            saved[column].fillna("").astype(str).tolist(),
                            expected[column].fillna("").astype(str).tolist(),
                        )


if __name__ == "__main__":
    unittest.main()
