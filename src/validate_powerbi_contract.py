"""Independently validate Phase 4A calculations and the Power BI data contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from train_models import IDENTIFIER_COLUMN, load_analytical_dataset


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "processed" / "telco_churn.duckdb"
DEFAULT_PHASE3A = PROJECT_ROOT / "artifacts" / "phase3a" / "v1"
DEFAULT_PHASE4A = PROJECT_ROOT / "outputs" / "powerbi" / "phase4a" / "v1"
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "retention_scenarios_v1.json"
DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "phase4b"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError(f"{label}: {actual} != {expected}")


def _validate_key(frame: pd.DataFrame, columns: list[str], table: str) -> None:
    if frame[columns].isna().any().any():
        raise ValueError(f"{table} primary key contains NULL")
    if frame.duplicated(columns).any():
        raise ValueError(f"{table} primary key is not unique: {columns}")


def _validate_types(
    frame: pd.DataFrame,
    table: str,
    integer_columns: list[str],
    decimal_columns: list[str],
    boolean_columns: list[str],
    text_columns: list[str],
) -> None:
    for column in integer_columns:
        values = pd.to_numeric(frame[column], errors="raise")
        if not np.all(np.isclose(values, np.round(values))):
            raise ValueError(f"{table}.{column} is not whole-number compatible")
    for column in decimal_columns:
        pd.to_numeric(frame[column], errors="raise")
    for column in boolean_columns:
        if not set(frame[column].dropna().astype(str).str.lower()).issubset(
            {"true", "false"}
        ):
            raise ValueError(f"{table}.{column} is not boolean compatible")
    for column in text_columns:
        if frame[column].isna().any():
            raise ValueError(f"{table}.{column} contains unexpected NULL text")


def load_sources(
    database_path: Path, phase3a_dir: Path, phase4a_dir: Path, config_path: Path
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, dict[str, Any], dict[str, str]]:
    names = [
        "capacity_performance",
        "scenario_assumptions",
        "scenario_outcomes",
        "break_even",
        "sensitivity_analysis",
        "customer_targeting",
    ]
    tables = {
        name: pd.read_csv(phase4a_dir / f"{name}_v1.csv") for name in names
    }
    recorded = json.loads(
        (phase4a_dir / "output_hashes_v1.json").read_text(encoding="utf-8")
    )
    hashes = {}
    for filename, expected in recorded.items():
        actual = sha256_file(phase4a_dir / filename)
        if actual != expected:
            raise ValueError(f"Phase 4A output hash mismatch: {filename}")
        hashes[filename] = actual

    predictions = pd.read_csv(phase3a_dir / "test_predictions_v1.csv").sort_values(
        "risk_rank", kind="mergesort"
    )
    analytical = load_analytical_dataset(database_path)
    source = predictions.merge(
        analytical[[IDENTIFIER_COLUMN, "monthly_charges"]],
        on=IDENTIFIER_COLUMN,
        validate="one_to_one",
    ).sort_values("risk_rank", kind="mergesort")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return tables, source, config, hashes


def validate_contract(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    specs = {
        "capacity_performance": {
            "power_bi_name": "DimCapacity",
            "grain": "one row per fixed contact capacity",
            "key": ["capacity_fraction"],
            "rows": 3,
            "integer": ["test_customers", "contacted_customers", "observed_churned_contacted", "total_test_churned"],
            "decimal": ["capacity_fraction", "observed_churn_capture", "precision", "test_prevalence", "lift"],
            "boolean": [],
            "text": ["capacity_label", "selection_rule"],
        },
        "scenario_assumptions": {
            "power_bi_name": "DimScenario",
            "grain": "one row per illustrative scenario",
            "key": ["name"],
            "rows": 3,
            "integer": ["benefit_horizon_months"],
            "decimal": ["contribution_margin_rate", "relative_risk_reduction", "contact_cost_per_customer", "offer_cost_per_customer"],
            "boolean": [],
            "text": ["name", "currency_unit", "effectiveness_definition", "offer_cost_incidence", "assumption_status"],
        },
        "scenario_outcomes": {
            "power_bi_name": "FactScenarioOutcome",
            "grain": "one row per scenario and fixed capacity",
            "key": ["scenario", "capacity_fraction"],
            "rows": 9,
            "integer": ["contacted_customers", "benefit_horizon_months"],
            "decimal": [column for column in tables["scenario_outcomes"].columns if column not in {"scenario", "capacity_label", "offer_cost_incidence", "contacted_customers", "benefit_horizon_months"}],
            "boolean": [],
            "text": ["scenario", "capacity_label", "offer_cost_incidence"],
        },
        "break_even": {
            "power_bi_name": "FactBreakEven",
            "grain": "one row per scenario and fixed capacity",
            "key": ["scenario", "capacity_fraction"],
            "rows": 9,
            "integer": ["contacted_customers", "benefit_horizon_months"],
            "decimal": [column for column in tables["break_even"].columns if column not in {"scenario", "capacity_label", "offer_cost_incidence", "contacted_customers", "benefit_horizon_months"}],
            "boolean": [],
            "text": ["scenario", "capacity_label", "offer_cost_incidence"],
        },
        "sensitivity_analysis": {
            "power_bi_name": "FactSensitivity",
            "grain": "one row per varied parameter, varied value, and fixed capacity",
            "key": ["varied_parameter", "varied_value", "capacity_fraction"],
            "rows": 66,
            "integer": ["contacted_customers"],
            "decimal": ["varied_value", "capacity_fraction", "net_expected_scenario_value", "gross_expected_retained_contribution", "total_campaign_cost", "expected_prevented_churn"],
            "boolean": [],
            "text": ["base_scenario", "varied_parameter", "capacity_label"],
        },
        "customer_targeting": {
            "power_bi_name": "FactTargetCustomer",
            "grain": "one row per held-out customer",
            "key": [IDENTIFIER_COLUMN],
            "rows": 1_409,
            "integer": ["risk_rank"],
            "decimal": ["predicted_probability", "monthly_charges", "base_expected_prevented_churn", "base_expected_gross_retained_contribution", "base_cost_if_contacted", "base_net_expected_value_if_contacted"],
            "boolean": ["selected_top_10pct", "selected_top_20pct", "selected_top_30pct"],
            "text": [IDENTIFIER_COLUMN],
        },
    }
    rows = []
    for name, spec in specs.items():
        frame = tables[name]
        if len(frame) != spec["rows"]:
            raise ValueError(f"{name} row count {len(frame)} != {spec['rows']}")
        _validate_key(frame, spec["key"], name)
        if frame.isna().any().any():
            raise ValueError(f"{name} contains unexpected NULL values")
        _validate_types(
            frame,
            name,
            spec["integer"],
            spec["decimal"],
            spec["boolean"],
            spec["text"],
        )
        rows.append(
            {
                "source_table": name,
                "power_bi_table": spec["power_bi_name"],
                "grain": spec["grain"],
                "primary_key": " + ".join(spec["key"]),
                "row_count": len(frame),
                "column_count": len(frame.columns),
                "duplicate_key_rows": int(frame.duplicated(spec["key"]).sum()),
                "null_cells": int(frame.isna().sum().sum()),
                "status": "PASS",
            }
        )
    if "actual_churn" in tables["customer_targeting"].columns:
        raise ValueError("Customer targeting export must not contain actual churn")
    if tables["customer_targeting"]["risk_rank"].nunique() != 1_409:
        raise ValueError("Risk rank must be unique")
    return pd.DataFrame(rows)


def reconcile_calculations(
    tables: dict[str, pd.DataFrame], source: pd.DataFrame, config: dict[str, Any]
) -> dict[str, int]:
    capacity = tables["capacity_performance"]
    scenario_assumptions = tables["scenario_assumptions"]
    outcomes = tables["scenario_outcomes"]
    break_even = tables["break_even"]
    sensitivity = tables["sensitivity_analysis"]
    targeting = tables["customer_targeting"].sort_values("risk_rank", kind="mergesort")
    assumptions = {row["name"]: row for row in config["scenarios"]}
    total_churned = int(source["actual_churn"].sum())
    prevalence = float(source["actual_churn"].mean())

    exported_assumptions = scenario_assumptions.set_index("name").to_dict("index")
    for name, scenario in assumptions.items():
        exported = exported_assumptions[name]
        for field in [
            "benefit_horizon_months",
            "contribution_margin_rate",
            "relative_risk_reduction",
            "contact_cost_per_customer",
            "offer_cost_per_customer",
        ]:
            _close(exported[field], scenario[field], f"{name} assumption {field}")
        if exported["currency_unit"] != config["currency_unit"]:
            raise ValueError(f"{name} currency unit does not match configuration")
        if exported["effectiveness_definition"] != config["effectiveness_definition"]:
            raise ValueError(f"{name} effectiveness definition does not match configuration")
        if exported["offer_cost_incidence"] != config["offer_cost_incidence"]:
            raise ValueError(f"{name} offer-cost incidence does not match configuration")
        if exported["assumption_status"] != "illustrative; not empirically validated":
            raise ValueError(f"{name} assumption status is not explicitly illustrative")

    for row in capacity.to_dict("records"):
        count = math.ceil(row["capacity_fraction"] * len(source))
        selected = source.iloc[:count]
        churned = int(selected["actual_churn"].sum())
        expected_label = f"Top {int(round(row['capacity_fraction'] * 100))}%"
        if row["capacity_label"] != expected_label:
            raise ValueError("Capacity label reconciliation failed")
        if row["test_customers"] != len(source) or row["total_test_churned"] != total_churned:
            raise ValueError("Capacity test-total reconciliation failed")
        if row["contacted_customers"] != count or row["observed_churned_contacted"] != churned:
            raise ValueError("Capacity count reconciliation failed")
        _close(row["observed_churn_capture"], churned / total_churned, "capture")
        _close(row["precision"], churned / count, "precision")
        _close(row["test_prevalence"], prevalence, "prevalence")
        _close(row["lift"], (churned / count) / prevalence, "lift")
        if row["selection_rule"] != "saved risk_rank <= ceil(capacity_fraction * test_customers)":
            raise ValueError("Capacity selection-rule reconciliation failed")

    for row in outcomes.to_dict("records"):
        scenario = assumptions[row["scenario"]]
        count = math.ceil(row["capacity_fraction"] * len(source))
        selected = source.iloc[:count]
        p = selected["predicted_probability"].to_numpy()
        charges = selected["monthly_charges"].to_numpy()
        e = scenario["relative_risk_reduction"]
        horizon = scenario["benefit_horizon_months"]
        margin = scenario["contribution_margin_rate"]
        full = float(np.sum(p * charges * horizon * margin))
        gross = full * e
        contact_cost = count * scenario["contact_cost_per_customer"]
        offer_cost = count * scenario["offer_cost_per_customer"]
        cost = contact_cost + offer_cost
        expected_prevented = float(np.sum(p * e))
        expected_label = f"Top {int(round(row['capacity_fraction'] * 100))}%"
        if row["capacity_label"] != expected_label or row["contacted_customers"] != count:
            raise ValueError("Scenario capacity reconciliation failed")
        for field in [
            "benefit_horizon_months",
            "contribution_margin_rate",
            "relative_risk_reduction",
            "contact_cost_per_customer",
            "offer_cost_per_customer",
        ]:
            _close(row[field], scenario[field], f"scenario {row['scenario']} {field}")
        if row["offer_cost_incidence"] != "every contacted customer":
            raise ValueError("Scenario offer-cost incidence reconciliation failed")
        _close(row["predicted_churn_sum_contacted"], float(np.sum(p)), "predicted churn sum")
        _close(row["average_predicted_churn_probability"], float(np.mean(p)), "average probability")
        _close(row["average_monthly_charges"], float(np.mean(charges)), "average charges")
        _close(row["expected_prevented_churn"], expected_prevented, "prevented churn")
        _close(row["probability_weighted_contribution_at_full_effect"], full, "full contribution")
        _close(row["gross_expected_retained_contribution"], gross, "gross contribution")
        _close(row["contact_cost_total"], contact_cost, "contact cost")
        _close(row["offer_cost_total"], offer_cost, "offer cost")
        _close(row["total_campaign_cost"], cost, "campaign cost")
        _close(row["net_expected_scenario_value"], gross - cost, "net value")
        _close(row["net_expected_value_per_contact"], (gross - cost) / count, "net per contact")
        _close(row["break_even_effectiveness"], cost / full, "break-even effectiveness")
        _close(row["break_even_total_cost_per_contact"], gross / count, "break-even total cost")
        _close(
            row["break_even_contact_cost_after_offer"],
            (gross / count) - scenario["offer_cost_per_customer"],
            "break-even contact cost",
        )

    for row in break_even.to_dict("records"):
        scenario = assumptions[row["scenario"]]
        count = math.ceil(row["capacity_fraction"] * len(source))
        selected = source.iloc[:count]
        full = float(
            np.sum(
                selected["predicted_probability"].to_numpy()
                * selected["monthly_charges"].to_numpy()
                * scenario["benefit_horizon_months"]
                * scenario["contribution_margin_rate"]
            )
        )
        gross = full * scenario["relative_risk_reduction"]
        cost_per_contact = (
            scenario["contact_cost_per_customer"] + scenario["offer_cost_per_customer"]
        )
        expected_label = f"Top {int(round(row['capacity_fraction'] * 100))}%"
        if row["capacity_label"] != expected_label or row["contacted_customers"] != count:
            raise ValueError("Break-even capacity reconciliation failed")
        for field in [
            "benefit_horizon_months",
            "contribution_margin_rate",
            "relative_risk_reduction",
            "contact_cost_per_customer",
            "offer_cost_per_customer",
        ]:
            _close(row[field], scenario[field], f"break-even {row['scenario']} {field}")
        if row["offer_cost_incidence"] != "every contacted customer":
            raise ValueError("Break-even offer-cost incidence reconciliation failed")
        _close(row["break_even_effectiveness"], count * cost_per_contact / full, "break-even effectiveness")
        _close(row["break_even_total_cost_per_contact"], gross / count, "break-even total cost")
        _close(
            row["break_even_contact_cost_after_offer"],
            (gross / count) - scenario["offer_cost_per_customer"],
            "break-even contact cost",
        )
        _close(row["current_total_cost_per_contact"], cost_per_contact, "current total cost")

    base = dict(assumptions["base"])
    for row in sensitivity.to_dict("records"):
        if row["base_scenario"] != "base":
            raise ValueError("Sensitivity base scenario reconciliation failed")
        if row["varied_parameter"] not in config["sensitivity"]:
            raise ValueError("Unknown sensitivity parameter")
        if not any(
            math.isclose(float(row["varied_value"]), float(value), rel_tol=0, abs_tol=1e-12)
            for value in config["sensitivity"][row["varied_parameter"]]
        ):
            raise ValueError("Sensitivity value is outside configured grid")
        scenario = dict(base)
        scenario[row["varied_parameter"]] = row["varied_value"]
        count = math.ceil(row["capacity_fraction"] * len(source))
        selected = source.iloc[:count]
        p = selected["predicted_probability"].to_numpy()
        charges = selected["monthly_charges"].to_numpy()
        e = scenario["relative_risk_reduction"]
        full = float(
            np.sum(
                p
                * charges
                * scenario["benefit_horizon_months"]
                * scenario["contribution_margin_rate"]
            )
        )
        gross = full * e
        cost = count * (
            scenario["contact_cost_per_customer"] + scenario["offer_cost_per_customer"]
        )
        expected_label = f"Top {int(round(row['capacity_fraction'] * 100))}%"
        if row["capacity_label"] != expected_label or row["contacted_customers"] != count:
            raise ValueError("Sensitivity capacity reconciliation failed")
        _close(row["gross_expected_retained_contribution"], gross, "sensitivity gross")
        _close(row["total_campaign_cost"], cost, "sensitivity cost")
        _close(row["net_expected_scenario_value"], gross - cost, "sensitivity net")
        _close(row["expected_prevented_churn"], float(np.sum(p * e)), "sensitivity prevented")

    if targeting[IDENTIFIER_COLUMN].tolist() != source[IDENTIFIER_COLUMN].tolist():
        raise ValueError("Customer targeting membership or risk order reconciliation failed")
    if not np.array_equal(targeting["risk_rank"].to_numpy(), np.arange(1, len(source) + 1)):
        raise ValueError("Customer targeting ranks are not contiguous")
    if not np.allclose(
        targeting["predicted_probability"], source["predicted_probability"], rtol=0, atol=1e-12
    ):
        raise ValueError("Customer targeting probabilities do not match frozen predictions")
    if not np.allclose(targeting["monthly_charges"], source["monthly_charges"], rtol=0, atol=1e-12):
        raise ValueError("Customer targeting charges do not match analytical data")
    base_effectiveness = base["relative_risk_reduction"]
    expected_prevented = source["predicted_probability"] * base_effectiveness
    expected_gross = (
        source["predicted_probability"]
        * source["monthly_charges"]
        * base["benefit_horizon_months"]
        * base["contribution_margin_rate"]
        * base_effectiveness
    )
    base_cost = base["contact_cost_per_customer"] + base["offer_cost_per_customer"]
    if not np.allclose(targeting["base_expected_prevented_churn"], expected_prevented, rtol=0, atol=1e-12):
        raise ValueError("Customer-level expected prevented churn reconciliation failed")
    if not np.allclose(targeting["base_expected_gross_retained_contribution"], expected_gross, rtol=0, atol=1e-9):
        raise ValueError("Customer-level gross contribution reconciliation failed")
    if not np.allclose(targeting["base_cost_if_contacted"], base_cost, rtol=0, atol=1e-12):
        raise ValueError("Customer-level cost reconciliation failed")
    if not np.allclose(targeting["base_net_expected_value_if_contacted"], expected_gross - base_cost, rtol=0, atol=1e-9):
        raise ValueError("Customer-level net value reconciliation failed")
    for fraction in config["capacities"]:
        column = f"selected_top_{int(round(fraction * 100))}pct"
        expected_flag = targeting["risk_rank"] <= math.ceil(fraction * len(source))
        if not np.array_equal(targeting[column].to_numpy(dtype=bool), expected_flag.to_numpy()):
            raise ValueError(f"Customer targeting flag reconciliation failed: {column}")

    return {
        "capacity_rows_reconciled": len(capacity),
        "scenario_rows_reconciled": len(outcomes),
        "break_even_rows_reconciled": len(break_even),
        "sensitivity_rows_reconciled": len(sensitivity),
    }


def validate_portability() -> dict[str, Any]:
    publishable = [
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "config" / "retention_scenarios_v1.json",
        PROJECT_ROOT / "docs" / "retention_strategy.md",
    ]
    forbidden = re.compile(r"[A-Za-z]:[\\/](?:Users|Documents)[\\/]", re.IGNORECASE)
    offending = []
    for path in publishable:
        if forbidden.search(path.read_text(encoding="utf-8")):
            offending.append(str(path.relative_to(PROJECT_ROOT)))
    ignored_manifests_with_absolute_paths = [
        "artifacts/phase3a/v1/run_manifest_v1.json",
        "artifacts/phase3b/v1/audit_manifest_v1.json",
        "outputs/powerbi/phase4a/v1/run_manifest_v1.json",
    ]
    if offending:
        raise ValueError(f"Publishable files contain personal absolute paths: {offending}")
    return {
        "publishable_files_checked": len(publishable),
        "publishable_absolute_path_violations": 0,
        "ignored_manifests_with_absolute_paths": ignored_manifests_with_absolute_paths,
        "required_power_bi_parameter": "DataRoot",
        "power_bi_path_rule": "File.Contents(DataRoot & relative_path)",
    }


def run_validation(
    database_path: Path,
    phase3a_dir: Path,
    phase4a_dir: Path,
    config_path: Path,
    artifact_root: Path,
    version: str,
) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise ValueError("Version contains invalid characters")
    target = artifact_root.resolve() / version
    if target.exists():
        raise FileExistsError(f"Validation artifact version already exists: {target}")
    artifact_root.mkdir(parents=True, exist_ok=True)
    tables, source, config, source_hashes = load_sources(
        database_path.resolve(), phase3a_dir.resolve(), phase4a_dir.resolve(), config_path.resolve()
    )
    contract = validate_contract(tables)
    reconciliation = reconcile_calculations(tables, source, config)
    portability = validate_portability()
    summary = {
        "status": "PASS",
        **reconciliation,
        "contract_tables_validated": len(contract),
        "phase4a_source_hashes": source_hashes,
        "portability": portability,
        "double_counting_controls": [
            "Use one selected capacity for KPIs; capacities are nested and non-additive.",
            "Use one selected scenario for static outcomes; scenario rows are alternatives and non-additive.",
            "Do not relate fact tables directly or enable bidirectional filters.",
            "Keep what-if parameter tables disconnected.",
            "Dynamic value measures must aggregate FactTargetCustomer exactly once by risk_rank.",
        ],
    }

    with tempfile.TemporaryDirectory(prefix=f".{version}-", dir=artifact_root.resolve()) as staging:
        stage = Path(staging)
        contract.to_csv(stage / f"table_contract_validation_{version}.csv", index=False)
        _write_json(stage / f"validation_summary_{version}.json", summary)
        hashes = {
            path.name: sha256_file(path) for path in stage.iterdir() if path.is_file()
        }
        _write_json(stage / f"artifact_hashes_{version}.json", hashes)
        stage.rename(target)
    print(json.dumps(reconciliation, indent=2, sort_keys=True))
    print(f"Contract tables validated: {len(contract)}")
    print(f"Validation artifacts: {target}")
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--phase3a-dir", type=Path, default=DEFAULT_PHASE3A)
    parser.add_argument("--phase4a-dir", type=Path, default=DEFAULT_PHASE4A)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--version", default="v1")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_validation(
        args.database,
        args.phase3a_dir,
        args.phase4a_dir,
        args.config,
        args.artifact_root,
        args.version,
    )


if __name__ == "__main__":
    main()
