"""Automated integrity checks for the reproducible DuckDB pipeline."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from prepare_data import (  # noqa: E402
    EXPECTED_CHURNED,
    EXPECTED_MISSING_TOTAL_CHARGES,
    EXPECTED_RETAINED,
    EXPECTED_ROWS,
    build_database,
)


class PipelineChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory()
        cls.database_path = Path(cls._temporary_directory.name) / "test.duckdb"
        cls.csv_path = PROJECT_ROOT / "data" / "raw" / "Telco-Customer-Churn.csv"
        cls.check_results = build_database(cls.csv_path, cls.database_path)
        cls.connection = duckdb.connect(str(cls.database_path), read_only=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.connection.close()
        cls._temporary_directory.cleanup()

    def test_row_counts_and_unique_customer_ids(self) -> None:
        raw_rows = self.connection.execute("SELECT COUNT(*) FROM raw.telco_churn").fetchone()[0]
        row_count, unique_ids = self.connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT customer_id) FROM analytics.customers"
        ).fetchone()
        self.assertEqual(raw_rows, EXPECTED_ROWS)
        self.assertEqual(row_count, EXPECTED_ROWS)
        self.assertEqual(unique_ids, EXPECTED_ROWS)

    def test_missing_values_and_safe_numeric_parsing(self) -> None:
        raw_blank_total, missing_total, parse_failures, tenure_zero_missing_total = self.connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM raw.telco_churn WHERE TRIM("TotalCharges") = ''),
                COUNT(*) FILTER (WHERE total_charges IS NULL),
                COUNT(*) FILTER (
                    WHERE customer_id IS NULL OR gender IS NULL OR senior_citizen IS NULL
                       OR partner IS NULL OR dependents IS NULL OR tenure_months IS NULL
                       OR phone_service IS NULL OR multiple_lines IS NULL OR internet_service IS NULL
                       OR online_security IS NULL OR online_backup IS NULL OR device_protection IS NULL
                       OR tech_support IS NULL OR streaming_tv IS NULL OR streaming_movies IS NULL
                       OR contract IS NULL OR paperless_billing IS NULL OR payment_method IS NULL
                       OR monthly_charges IS NULL OR churned IS NULL
                ),
                COUNT(*) FILTER (WHERE total_charges IS NULL AND tenure_months = 0)
            FROM analytics.customers
            """
        ).fetchone()
        self.assertEqual(raw_blank_total, EXPECTED_MISSING_TOTAL_CHARGES)
        self.assertEqual(missing_total, EXPECTED_MISSING_TOTAL_CHARGES)
        self.assertEqual(parse_failures, 0)
        self.assertEqual(tenure_zero_missing_total, EXPECTED_MISSING_TOTAL_CHARGES)

    def test_original_csv_hash_is_unchanged(self) -> None:
        with self.csv_path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        self.assertEqual(
            digest,
            "16320c9c1ec72448db59aa0a26a0b95401046bef5d02fd3aeb906448e3055e91",
        )

    def test_churn_totals(self) -> None:
        churned, retained, missing_target = self.connection.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE churned),
                COUNT(*) FILTER (WHERE NOT churned),
                COUNT(*) FILTER (WHERE churned IS NULL)
            FROM analytics.customers
            """
        ).fetchone()
        self.assertEqual(churned, EXPECTED_CHURNED)
        self.assertEqual(retained, EXPECTED_RETAINED)
        self.assertEqual(missing_target, 0)

    def test_each_segment_reconciles_to_dataset_totals(self) -> None:
        results = self.connection.execute(
            """
            SELECT segment, SUM(group_size), SUM(churned_customers)
            FROM analytics.churn_by_segment
            GROUP BY segment
            ORDER BY segment
            """
        ).fetchall()
        self.assertEqual(len(results), 12)
        for segment, customers, churned in results:
            with self.subTest(segment=segment):
                self.assertEqual(customers, EXPECTED_ROWS)
                self.assertEqual(churned, EXPECTED_CHURNED)

    def test_customer_id_is_identifier_not_segment(self) -> None:
        dimensions = {
            row[0]
            for row in self.connection.execute(
                "SELECT DISTINCT segment FROM analytics.churn_by_segment"
            ).fetchall()
        }
        self.assertNotIn("customer_id", dimensions)


if __name__ == "__main__":
    unittest.main()
