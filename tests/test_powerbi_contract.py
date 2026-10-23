"""Checks for the independently validated Phase 4B Power BI contract."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from validate_powerbi_contract import (  # noqa: E402
    DEFAULT_CONFIG,
    DEFAULT_DATABASE,
    DEFAULT_PHASE3A,
    DEFAULT_PHASE4A,
    load_sources,
    reconcile_calculations,
    sha256_file,
    validate_contract,
    validate_portability,
)


class PowerBIContractChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = PROJECT_ROOT / "artifacts" / "phase4b" / "v1"
        cls.summary = json.loads(
            (cls.artifact / "validation_summary_v1.json").read_text(encoding="utf-8")
        )
        cls.contract = pd.read_csv(
            cls.artifact / "table_contract_validation_v1.csv"
        )

    def test_all_calculation_rows_reconciled(self) -> None:
        self.assertEqual(self.summary["capacity_rows_reconciled"], 3)
        self.assertEqual(self.summary["scenario_rows_reconciled"], 9)
        self.assertEqual(self.summary["break_even_rows_reconciled"], 9)
        self.assertEqual(self.summary["sensitivity_rows_reconciled"], 66)
        self.assertEqual(self.summary["status"], "PASS")

    def test_all_contracts_pass_with_unique_non_null_keys(self) -> None:
        self.assertEqual(len(self.contract), 6)
        self.assertTrue((self.contract["status"] == "PASS").all())
        self.assertTrue((self.contract["duplicate_key_rows"] == 0).all())
        self.assertTrue((self.contract["null_cells"] == 0).all())

    def test_phase4a_exports_are_unchanged(self) -> None:
        for filename, expected in self.summary["phase4a_source_hashes"].items():
            with self.subTest(filename=filename):
                self.assertEqual(sha256_file(DEFAULT_PHASE4A / filename), expected)

    def test_independent_recalculation_still_passes(self) -> None:
        tables, source, config, _ = load_sources(
            DEFAULT_DATABASE, DEFAULT_PHASE3A, DEFAULT_PHASE4A, DEFAULT_CONFIG
        )
        contract = validate_contract(tables)
        results = reconcile_calculations(tables, source, config)
        self.assertEqual(len(contract), 6)
        self.assertEqual(results["scenario_rows_reconciled"], 9)

    def test_publishable_path_contract_is_portable(self) -> None:
        result = validate_portability()
        self.assertEqual(result["publishable_absolute_path_violations"], 0)
        self.assertEqual(result["required_power_bi_parameter"], "DataRoot")
        self.assertGreater(len(result["ignored_manifests_with_absolute_paths"]), 0)


if __name__ == "__main__":
    unittest.main()
