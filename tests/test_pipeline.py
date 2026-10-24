"""Automated integrity checks for the reproducible DuckDB pipeline."""

from __future__ import annotations

import shutil
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
from source_provenance import (  # noqa: E402
    EXPECTED_IBM_TELCO_CSV_SHA256,
    IBM_TELCO_DATASET_KEY,
    sha256_file,
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
        self.assertEqual(sha256_file(self.csv_path), EXPECTED_IBM_TELCO_CSV_SHA256)

    def test_verified_source_provenance_is_persisted(self) -> None:
        rows = self.connection.execute(
            """
            SELECT dataset_key, source_csv_sha256
            FROM metadata.source_provenance
            """
        ).fetchall()
        self.assertEqual(
            rows,
            [(IBM_TELCO_DATASET_KEY, EXPECTED_IBM_TELCO_CSV_SHA256)],
        )

    def test_byte_modified_csv_is_rejected_before_database_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            modified_csv = temporary_root / self.csv_path.name
            rejected_database = temporary_root / "rejected.duckdb"
            shutil.copyfile(self.csv_path, modified_csv)

            content = modified_csv.read_bytes()
            original_value = b"29.85"
            replacement_value = b"29.86"
            self.assertIn(original_value, content)
            modified_csv.write_bytes(content.replace(original_value, replacement_value, 1))

            with self.assertRaisesRegex(ValueError, "Unexpected source CSV SHA-256"):
                build_database(modified_csv, rejected_database)
            self.assertFalse(rejected_database.exists())

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
