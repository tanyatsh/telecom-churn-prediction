"""Consistency checks for the frozen-model Phase 3B audit."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from audit_model import sha256_file  # noqa: E402
from train_models import EXCLUDED_COLUMNS, FEATURE_COLUMNS  # noqa: E402


class ModelAuditChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.phase3a = PROJECT_ROOT / "artifacts" / "phase3a" / "v1"
        cls.audit = PROJECT_ROOT / "artifacts" / "phase3b" / "v1"
        required = [
            "permutation_importance_v1.csv",
            "logistic_coefficients_v1.csv",
            "subgroup_performance_v1.csv",
            "risk_deciles_v1.csv",
            "calibration_summary_v1.json",
            "audit_manifest_v1.json",
        ]
        missing = [name for name in required if not (cls.audit / name).is_file()]
        if missing:
            raise FileNotFoundError(f"Run src/audit_model.py first; missing: {missing}")
        cls.permutation = pd.read_csv(cls.audit / "permutation_importance_v1.csv")
        cls.coefficients = pd.read_csv(cls.audit / "logistic_coefficients_v1.csv")
        cls.subgroups = pd.read_csv(cls.audit / "subgroup_performance_v1.csv")
        cls.risk = pd.read_csv(cls.audit / "risk_deciles_v1.csv")
        cls.calibration = json.loads(
            (cls.audit / "calibration_summary_v1.json").read_text(encoding="utf-8")
        )
        cls.manifest = json.loads(
            (cls.audit / "audit_manifest_v1.json").read_text(encoding="utf-8")
        )

    def test_phase3a_artifacts_are_unchanged(self) -> None:
        for name, expected_hash in self.manifest["phase3a_source_hashes"].items():
            with self.subTest(name=name):
                self.assertEqual(sha256_file(self.phase3a / name), expected_hash)
        self.assertEqual(self.manifest["model_fit_calls"], 0)

    def test_original_feature_permutation_output(self) -> None:
        self.assertEqual(set(self.permutation["feature"]), set(FEATURE_COLUMNS))
        self.assertEqual(len(self.permutation), len(FEATURE_COLUMNS))
        self.assertTrue(set(EXCLUDED_COLUMNS).isdisjoint(self.permutation["feature"]))
        self.assertTrue((self.permutation["repeats"] == 20).all())

    def test_coefficients_reconcile_with_frozen_model(self) -> None:
        model = joblib.load(self.phase3a / "churn_model_v1.joblib")
        expected = model.named_steps["model"].coef_.reshape(-1)
        ordered = self.coefficients.sort_values("absolute_rank")
        np.testing.assert_allclose(ordered["coefficient"].to_numpy(), expected[np.argsort(-np.abs(expected))], atol=1e-14, rtol=0.0)
        self.assertTrue(set(EXCLUDED_COLUMNS).isdisjoint(self.coefficients["original_feature"]))

    def test_each_subgroup_dimension_reconciles(self) -> None:
        for dimension, group in self.subgroups.groupby("dimension"):
            with self.subTest(dimension=dimension):
                self.assertEqual(int(group["group_size"].sum()), 1_409)
                self.assertEqual(int(group["churned_count"].sum()), 374)
                self.assertEqual(int(group["retained_count"].sum()), 1_035)

    def test_risk_deciles_and_calibration_reconcile(self) -> None:
        self.assertEqual(set(self.risk["calibration_decile"]), set(range(1, 11)))
        self.assertEqual(int(self.risk["group_size"].sum()), 1_409)
        self.assertEqual(int(self.risk["churned_count"].sum()), 374)
        self.assertAlmostEqual(
            self.calibration["expected_calibration_error_10_equal_count_bins"],
            self.calibration["phase3a_recorded_ece"],
            places=14,
        )


if __name__ == "__main__":
    unittest.main()
