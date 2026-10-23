"""Run named SQL EDA queries and export their results as CSV files."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "processed" / "telco_churn.duckdb"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "eda"
QUERY_FILE = PROJECT_ROOT / "sql" / "02_eda_queries.sql"
QUERY_HEADER = re.compile(r"^\s*--\s*name:\s*([a-z0-9_]+)\s*$", re.IGNORECASE)


def load_named_queries(path: Path) -> dict[str, str]:
    queries: dict[str, str] = {}
    current_name: str | None = None
    current_lines: list[str] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        match = QUERY_HEADER.match(line)
        if match:
            if current_name is not None:
                queries[current_name] = "\n".join(current_lines).strip().rstrip(";")
            current_name = match.group(1).lower()
            current_lines = []
        elif current_name is not None:
            current_lines.append(line)

    if current_name is not None:
        queries[current_name] = "\n".join(current_lines).strip().rstrip(";")
    if not queries or any(not query for query in queries.values()):
        raise ValueError(f"No valid named queries found in {path}")
    return queries


def export_results(database_path: Path, output_dir: Path) -> list[Path]:
    if not database_path.is_file():
        raise FileNotFoundError(
            f"DuckDB database not found: {database_path}. Run src/prepare_data.py first."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        for name, query in load_named_queries(QUERY_FILE).items():
            cursor = connection.execute(query)
            headers = [description[0] for description in cursor.description]
            path = output_dir / f"{name}.csv"
            with path.open("w", encoding="utf-8", newline="") as output:
                writer = csv.writer(output)
                writer.writerow(headers)
                writer.writerows(cursor.fetchall())
            written.append(path)
    finally:
        connection.close()
    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    written = export_results(args.database.resolve(), args.output_dir.resolve())
    print(f"Exported {len(written)} query results:")
    for path in written:
        print(path)


if __name__ == "__main__":
    main()
