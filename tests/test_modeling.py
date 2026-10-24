"""Integrity and reproducibility checks for Phase 3A artifacts."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import joblib
import duckdb
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from train_models import (  # noqa: E402
    EXCLUDED_COLUMNS,
    FEATURE_COLUMNS,
    IDENTIFIER_COLUMN,
    TARGET_COLUMN,
    create_split_membership,
    load_analytical_dataset,
    load_verified_source_sha256,
    train_and_evaluate,
)
from source_provenance import (  # noqa: E402
    EXPECTED_IBM_TELCO_CSV_SHA256,
    IBM_TELCO_DATASET_KEY,
)


class ModelingArtifactChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.database_path = PROJECT_ROOT / "data" / "processed" / "telco_churn.duckdb"
        cls.artifact_dir = PROJECT_ROOT / "artifacts" / "phase3a" / "v1"
        required = [
            "split_membership_v1.csv",
            "test_predictions_v1.csv",
            "churn_model_v1.joblib",
            "feature_manifest_v1.json",
            "run_manifest_v1.json",
        ]
        missing = [name for name in required if not (cls.artifact_dir / name).is_file()]
        if missing:
            raise FileNotFoundError(f"Run src/train_models.py first; missing artifacts: {missing}")

        cls.data = load_analytical_dataset(cls.database_path)
        cls.membership = pd.read_csv(cls.artifact_dir / "split_membership_v1.csv")
        cls.predictions = pd.read_csv(cls.artifact_dir / "test_predictions_v1.csv")
        cls.model = joblib.load(cls.artifact_dir / "churn_model_v1.joblib")
        cls.feature_manifest = json.loads(
            (cls.artifact_dir / "feature_manifest_v1.json").read_text(encoding="utf-8")
        )
        cls.run_manifest = json.loads(
            (cls.artifact_dir / "run_manifest_v1.json").read_text(encoding="utf-8")
        )

    def test_split_integrity(self) -> None:
        self.assertEqual(len(self.membership), len(self.data))
        self.assertEqual(self.membership[IDENTIFIER_COLUMN].nunique(), len(self.data))
        self.assertEqual(set(self.membership["split"]), {"train", "test"})
        counts = self.membership["split"].value_counts().to_dict()
        self.assertEqual(counts, {"train": 5_634, "test": 1_409})
        train_ids = set(
            self.membership.loc[self.membership["split"] == "train", IDENTIFIER_COLUMN]
        )
        test_ids = set(
            self.membership.loc[self.membership["split"] == "test", IDENTIFIER_COLUMN]
        )
        self.assertTrue(train_ids.isdisjoint(test_ids))
        self.assertEqual(train_ids | test_ids, set(self.data[IDENTIFIER_COLUMN]))

    def test_leakage_columns_are_excluded(self) -> None:
        self.assertEqual(self.feature_manifest["included_features"], FEATURE_COLUMNS)
        self.assertEqual(self.feature_manifest["excluded_columns"], EXCLUDED_COLUMNS)
        self.assertTrue(set(EXCLUDED_COLUMNS).isdisjoint(FEATURE_COLUMNS))
        self.assertEqual(list(self.model.feature_names_in_), FEATURE_COLUMNS)

    def test_prediction_count_and_test_membership(self) -> None:
        test_ids = set(
            self.membership.loc[self.membership["split"] == "test", IDENTIFIER_COLUMN]
        )
        self.assertEqual(len(self.predictions), 1_409)
        self.assertEqual(self.predictions[IDENTIFIER_COLUMN].nunique(), 1_409)
        self.assertEqual(set(self.predictions[IDENTIFIER_COLUMN]), test_ids)

    def test_split_generation_is_deterministic(self) -> None:
        first = create_split_membership(self.data)
        second = create_split_membership(self.data.sample(frac=1.0, random_state=7))
        pd.testing.assert_frame_equal(first, second)
        pd.testing.assert_frame_equal(first, self.membership)

    def test_saved_predictions_are_deterministic(self) -> None:
        test_rows = (
            self.data.merge(self.membership, on=IDENTIFIER_COLUMN, validate="one_to_one")
            .loc[lambda frame: frame["split"] == "test"]
            .sort_values(IDENTIFIER_COLUMN, kind="mergesort")
        )
        features = test_rows[FEATURE_COLUMNS]
        first = self.model.predict_proba(features)[:, 1]
        second = self.model.predict_proba(features)[:, 1]
        stored = self.predictions.sort_values(IDENTIFIER_COLUMN)["predicted_probability"].to_numpy()
        np.testing.assert_array_equal(first, second)
        np.testing.assert_allclose(first, stored, rtol=0.0, atol=1e-14)

    def test_missing_total_charges_reach_the_pipeline_input(self) -> None:
        self.assertEqual(int(self.data["total_charges"].isna().sum()), 11)
        numeric_pipeline = self.model.named_steps["preprocess"].named_transformers_["numeric"]
        self.assertIn("imputer", numeric_pipeline.named_steps)

    def test_training_manifest_uses_verified_database_provenance(self) -> None:
        verified_sha256 = load_verified_source_sha256(self.database_path)
        self.assertEqual(verified_sha256, EXPECTED_IBM_TELCO_CSV_SHA256)
        self.assertEqual(self.run_manifest["raw_csv_sha256"], verified_sha256)

    def test_missing_database_provenance_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "missing.duckdb"
            connection = duckdb.connect(str(database_path))
            connection.close()
            with self.assertRaisesRegex(ValueError, "provenance is missing or unreadable"):
                train_and_evaluate(
                    database_path,
                    Path(temporary_directory) / "artifacts",
                    "missing-provenance",
                )

    def test_incorrect_database_provenance_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "incorrect.duckdb"
            connection = duckdb.connect(str(database_path))
            try:
                connection.execute("CREATE SCHEMA metadata")
                connection.execute(
                    """
                    CREATE TABLE metadata.source_provenance (
                        dataset_key VARCHAR NOT NULL,
                        source_csv_sha256 VARCHAR NOT NULL
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO metadata.source_provenance VALUES (?, ?)",
                    [IBM_TELCO_DATASET_KEY, "0" * 64],
                )
            finally:
                connection.close()

            with self.assertRaisesRegex(ValueError, "Unexpected DuckDB source provenance"):
                train_and_evaluate(
                    database_path,
                    Path(temporary_directory) / "artifacts",
                    "incorrect-provenance",
                )


if __name__ == "__main__":
    unittest.main()
