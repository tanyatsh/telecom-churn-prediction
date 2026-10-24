"""Build the Phase 2 DuckDB database from the immutable IBM Telco CSV."""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

from source_provenance import (
    EXPECTED_IBM_TELCO_CSV_SHA256,
    IBM_TELCO_DATASET_KEY,
    sha256_file,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = PROJECT_ROOT / "data" / "raw" / "Telco-Customer-Churn.csv"
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "processed" / "telco_churn.duckdb"
PREPARE_SQL = PROJECT_ROOT / "sql" / "01_prepare.sql"

EXPECTED_ROWS = 7_043
EXPECTED_CHURNED = 1_869
EXPECTED_RETAINED = 5_174
EXPECTED_MISSING_TOTAL_CHARGES = 11


def _sql_string(value: Path) -> str:
    return value.resolve().as_posix().replace("'", "''")


def run_checks(connection: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Validate source-specific invariants and aggregate reconciliation."""
    row = connection.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM raw.telco_churn) AS raw_rows,
            COUNT(*) AS analytical_rows,
            COUNT(DISTINCT customer_id) AS unique_customer_ids,
            COUNT(*) FILTER (WHERE customer_id IS NULL) AS missing_customer_ids,
            COUNT(*) FILTER (WHERE total_charges IS NULL) AS missing_total_charges,
            COUNT(*) FILTER (WHERE churned) AS churned_customers,
            COUNT(*) FILTER (WHERE NOT churned) AS retained_customers,
            COUNT(*) FILTER (
                WHERE customer_id IS NULL
                   OR gender IS NULL
                   OR senior_citizen IS NULL
                   OR partner IS NULL
                   OR dependents IS NULL
                   OR tenure_months IS NULL
                   OR phone_service IS NULL
                   OR multiple_lines IS NULL
                   OR internet_service IS NULL
                   OR online_security IS NULL
                   OR online_backup IS NULL
                   OR device_protection IS NULL
                   OR tech_support IS NULL
                   OR streaming_tv IS NULL
                   OR streaming_movies IS NULL
                   OR contract IS NULL
                   OR paperless_billing IS NULL
                   OR payment_method IS NULL
                   OR monthly_charges IS NULL
                   OR churned IS NULL
                   OR tenure_band = 'Unknown'
                   OR monthly_charge_band = 'Unknown'
            ) AS required_parse_failures
        FROM analytics.customers
        """
    ).fetchone()

    keys = [
        "raw_rows",
        "analytical_rows",
        "unique_customer_ids",
        "missing_customer_ids",
        "missing_total_charges",
        "churned_customers",
        "retained_customers",
        "required_parse_failures",
    ]
    results = dict(zip(keys, row, strict=True))

    expected = {
        "raw_rows": EXPECTED_ROWS,
        "analytical_rows": EXPECTED_ROWS,
        "unique_customer_ids": EXPECTED_ROWS,
        "missing_customer_ids": 0,
        "missing_total_charges": EXPECTED_MISSING_TOTAL_CHARGES,
        "churned_customers": EXPECTED_CHURNED,
        "retained_customers": EXPECTED_RETAINED,
        "required_parse_failures": 0,
    }
    for key, expected_value in expected.items():
        if results[key] != expected_value:
            raise ValueError(f"Check failed for {key}: {results[key]} != {expected_value}")

    reconciliations = connection.execute(
        """
        SELECT
            segment,
            SUM(group_size) AS customers,
            SUM(churned_customers) AS churned_customers
        FROM analytics.churn_by_segment
        GROUP BY segment
        """
    ).fetchall()
    for segment, customers, churned_customers in reconciliations:
        if customers != EXPECTED_ROWS or churned_customers != EXPECTED_CHURNED:
            raise ValueError(
                f"Aggregate reconciliation failed for {segment}: "
                f"customers={customers}, churned={churned_customers}"
            )
    results["reconciled_segments"] = len(reconciliations)
    if results["reconciled_segments"] != 12:
        raise ValueError("Expected 12 reconciled segment dimensions")
    return results


def build_database(csv_path: Path, database_path: Path) -> dict[str, int]:
    """Create raw and analytical DuckDB objects, rolling back on failed checks."""
    csv_path = csv_path.resolve()
    database_path = database_path.resolve()
    if not csv_path.is_file():
        raise FileNotFoundError(f"Raw CSV not found: {csv_path}")

    actual_sha256 = sha256_file(csv_path)
    if actual_sha256 != EXPECTED_IBM_TELCO_CSV_SHA256:
        raise ValueError(
            "Unexpected source CSV SHA-256: "
            f"{actual_sha256} != {EXPECTED_IBM_TELCO_CSV_SHA256}"
        )

    database_path.parent.mkdir(parents=True, exist_ok=True)

    sql = PREPARE_SQL.read_text(encoding="utf-8").format(csv_path=_sql_string(csv_path))
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute("BEGIN TRANSACTION")
        connection.execute(sql)
        connection.execute("CREATE SCHEMA IF NOT EXISTS metadata")
        connection.execute(
            """
            CREATE OR REPLACE TABLE metadata.source_provenance (
                dataset_key VARCHAR NOT NULL,
                source_csv_sha256 VARCHAR NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO metadata.source_provenance VALUES (?, ?)",
            [IBM_TELCO_DATASET_KEY, actual_sha256],
        )
        results = run_checks(connection)
        connection.execute("COMMIT")
        return results
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = build_database(args.csv, args.database)
    print(f"Built {args.database.resolve()}")
    for key, value in results.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
