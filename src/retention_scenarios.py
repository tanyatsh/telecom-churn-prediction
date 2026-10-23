"""Evaluate fixed risk capacities and hypothetical retention-value scenarios."""

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
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "retention_scenarios_v1.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "powerbi" / "phase4a"
EXPECTED_TEST_CUSTOMERS = 1_409
EXPECTED_TEST_CHURNED = 374


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    capacities = config.get("capacities", [])
    if capacities != sorted(capacities) or any(not 0 < value <= 1 for value in capacities):
        raise ValueError("Capacities must be unique ascending fractions in (0, 1]")
    if len(set(capacities)) != len(capacities):
        raise ValueError("Capacities must be unique")
    names = [scenario["name"] for scenario in config.get("scenarios", [])]
    if len(names) != len(set(names)) or "base" not in names:
        raise ValueError("Scenario names must be unique and include 'base'")
    for scenario in config["scenarios"]:
        validate_assumptions(scenario)
    return config


def validate_assumptions(assumptions: dict[str, Any]) -> None:
    if assumptions["benefit_horizon_months"] <= 0:
        raise ValueError("Benefit horizon must be positive")
    if not 0 < assumptions["contribution_margin_rate"] <= 1:
        raise ValueError("Contribution margin rate must be in (0, 1]")
    if not 0 <= assumptions["relative_risk_reduction"] <= 1:
        raise ValueError("Relative risk reduction must be in [0, 1]")
    if assumptions["contact_cost_per_customer"] < 0:
        raise ValueError("Contact cost cannot be negative")
    if assumptions["offer_cost_per_customer"] < 0:
        raise ValueError("Offer cost cannot be negative")


def load_frozen_test_customers(
    database_path: Path, phase3a_dir: Path
) -> tuple[pd.DataFrame, dict[str, str]]:
    recorded_hashes = json.loads(
        (phase3a_dir / "artifact_hashes_v1.json").read_text(encoding="utf-8")
    )
    current_hashes: dict[str, str] = {}
    for name, expected in recorded_hashes.items():
        actual = sha256_file(phase3a_dir / name)
        if actual != expected:
            raise ValueError(f"Frozen Phase 3A artifact hash mismatch: {name}")
        current_hashes[name] = actual

    predictions = pd.read_csv(phase3a_dir / "test_predictions_v1.csv")
    metrics = json.loads((phase3a_dir / "test_metrics_v1.json").read_text(encoding="utf-8"))
    data = load_analytical_dataset(database_path)
    customers = predictions.merge(
        data[[IDENTIFIER_COLUMN, "monthly_charges"]],
        on=IDENTIFIER_COLUMN,
        how="left",
        validate="one_to_one",
    )
    if len(customers) != EXPECTED_TEST_CUSTOMERS or customers[IDENTIFIER_COLUMN].nunique() != EXPECTED_TEST_CUSTOMERS:
        raise ValueError("Frozen test customer count failed")
    if int(customers["actual_churn"].sum()) != EXPECTED_TEST_CHURNED:
        raise ValueError("Frozen test churn total failed")
    if customers["monthly_charges"].isna().any():
        raise ValueError("Monthly charges must be present for every test customer")

    expected_ranking = customers.sort_values(
        ["predicted_probability", IDENTIFIER_COLUMN],
        ascending=[False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    expected_ranking["expected_rank"] = np.arange(1, len(expected_ranking) + 1)
    if not np.array_equal(expected_ranking["risk_rank"], expected_ranking["expected_rank"]):
        raise ValueError("Frozen risk ranks are inconsistent with probability and ID tie-break")
    if not math.isclose(
        float(customers["actual_churn"].mean()),
        float(metrics["test_prevalence"]),
        rel_tol=0.0,
        abs_tol=1e-15,
    ):
        raise ValueError("Frozen prevalence does not reconcile")
    return expected_ranking.drop(columns="expected_rank"), current_hashes


def contacted_count(total_customers: int, capacity: float) -> int:
    return math.ceil(total_customers * capacity)


def capacity_performance(customers: pd.DataFrame, capacities: list[float]) -> pd.DataFrame:
    total_churned = int(customers["actual_churn"].sum())
    prevalence = float(customers["actual_churn"].mean())
    rows = []
    for capacity in capacities:
        count = contacted_count(len(customers), capacity)
        selected = customers.iloc[:count]
        observed_churned = int(selected["actual_churn"].sum())
        precision = observed_churned / count
        rows.append(
            {
                "capacity_fraction": capacity,
                "capacity_label": f"Top {capacity:.0%}",
                "test_customers": len(customers),
                "contacted_customers": count,
                "observed_churned_contacted": observed_churned,
                "total_test_churned": total_churned,
                "observed_churn_capture": observed_churned / total_churned,
                "precision": precision,
                "test_prevalence": prevalence,
                "lift": precision / prevalence,
                "selection_rule": "saved risk_rank <= ceil(capacity_fraction * test_customers)",
            }
        )
    return pd.DataFrame(rows)


def calculate_scenario(
    selected: pd.DataFrame, assumptions: dict[str, Any]
) -> dict[str, float]:
    validate_assumptions(assumptions)
    probabilities = selected["predicted_probability"].to_numpy(dtype=float)
    monthly_charges = selected["monthly_charges"].to_numpy(dtype=float)
    effectiveness = float(assumptions["relative_risk_reduction"])
    horizon = float(assumptions["benefit_horizon_months"])
    margin = float(assumptions["contribution_margin_rate"])
    contact_cost = float(assumptions["contact_cost_per_customer"])
    offer_cost = float(assumptions["offer_cost_per_customer"])

    probability_weighted_contribution_at_full_effect = float(
        np.sum(probabilities * monthly_charges * horizon * margin)
    )
    expected_prevented_churn = float(np.sum(probabilities * effectiveness))
    gross_expected_retained_contribution = (
        probability_weighted_contribution_at_full_effect * effectiveness
    )
    contact_cost_total = len(selected) * contact_cost
    offer_cost_total = len(selected) * offer_cost
    total_campaign_cost = contact_cost_total + offer_cost_total
    net_expected_scenario_value = gross_expected_retained_contribution - total_campaign_cost
    break_even_effectiveness = (
        total_campaign_cost / probability_weighted_contribution_at_full_effect
        if probability_weighted_contribution_at_full_effect > 0
        else math.nan
    )
    break_even_total_cost_per_contact = (
        gross_expected_retained_contribution / len(selected) if len(selected) else math.nan
    )
    break_even_contact_cost_after_offer = break_even_total_cost_per_contact - offer_cost
    return {
        "predicted_churn_sum_contacted": float(probabilities.sum()),
        "average_predicted_churn_probability": float(probabilities.mean()),
        "average_monthly_charges": float(monthly_charges.mean()),
        "expected_prevented_churn": expected_prevented_churn,
        "probability_weighted_contribution_at_full_effect": probability_weighted_contribution_at_full_effect,
        "gross_expected_retained_contribution": gross_expected_retained_contribution,
        "contact_cost_total": contact_cost_total,
        "offer_cost_total": offer_cost_total,
        "total_campaign_cost": total_campaign_cost,
        "net_expected_scenario_value": net_expected_scenario_value,
        "net_expected_value_per_contact": net_expected_scenario_value / len(selected),
        "break_even_effectiveness": break_even_effectiveness,
        "break_even_total_cost_per_contact": break_even_total_cost_per_contact,
        "break_even_contact_cost_after_offer": break_even_contact_cost_after_offer,
    }


def scenario_tables(
    customers: pd.DataFrame, capacities: list[float], scenarios: list[dict[str, Any]]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    outcomes = []
    break_even = []
    for scenario in scenarios:
        for capacity in capacities:
            count = contacted_count(len(customers), capacity)
            selected = customers.iloc[:count]
            calculation = calculate_scenario(selected, scenario)
            base = {
                "scenario": scenario["name"],
                "capacity_fraction": capacity,
                "capacity_label": f"Top {capacity:.0%}",
                "contacted_customers": count,
                "benefit_horizon_months": scenario["benefit_horizon_months"],
                "contribution_margin_rate": scenario["contribution_margin_rate"],
                "relative_risk_reduction": scenario["relative_risk_reduction"],
                "contact_cost_per_customer": scenario["contact_cost_per_customer"],
                "offer_cost_per_customer": scenario["offer_cost_per_customer"],
                "offer_cost_incidence": "every contacted customer",
            }
            outcomes.append(base | calculation)
            break_even.append(
                base
                | {
                    "break_even_effectiveness": calculation["break_even_effectiveness"],
                    "break_even_total_cost_per_contact": calculation[
                        "break_even_total_cost_per_contact"
                    ],
                    "break_even_contact_cost_after_offer": calculation[
                        "break_even_contact_cost_after_offer"
                    ],
                    "current_total_cost_per_contact": scenario[
                        "contact_cost_per_customer"
                    ]
                    + scenario["offer_cost_per_customer"],
                }
            )
    return pd.DataFrame(outcomes), pd.DataFrame(break_even)


def sensitivity_table(
    customers: pd.DataFrame,
    capacities: list[float],
    base: dict[str, Any],
    sensitivity: dict[str, list[float]],
) -> pd.DataFrame:
    rows = []
    for parameter, values in sensitivity.items():
        for value in values:
            assumptions = dict(base)
            assumptions[parameter] = value
            for capacity in capacities:
                count = contacted_count(len(customers), capacity)
                calculation = calculate_scenario(customers.iloc[:count], assumptions)
                rows.append(
                    {
                        "base_scenario": base["name"],
                        "varied_parameter": parameter,
                        "varied_value": value,
                        "capacity_fraction": capacity,
                        "capacity_label": f"Top {capacity:.0%}",
                        "contacted_customers": count,
                        "net_expected_scenario_value": calculation[
                            "net_expected_scenario_value"
                        ],
                        "gross_expected_retained_contribution": calculation[
                            "gross_expected_retained_contribution"
                        ],
                        "total_campaign_cost": calculation["total_campaign_cost"],
                        "expected_prevented_churn": calculation["expected_prevented_churn"],
                    }
                )
    return pd.DataFrame(rows)


def customer_targeting_table(
    customers: pd.DataFrame, capacities: list[float], base: dict[str, Any]
) -> pd.DataFrame:
    table = customers[
        [IDENTIFIER_COLUMN, "risk_rank", "predicted_probability", "monthly_charges"]
    ].copy()
    for capacity in capacities:
        count = contacted_count(len(customers), capacity)
        table[f"selected_top_{int(capacity * 100)}pct"] = table["risk_rank"] <= count

    effectiveness = float(base["relative_risk_reduction"])
    horizon = float(base["benefit_horizon_months"])
    margin = float(base["contribution_margin_rate"])
    cost = float(base["contact_cost_per_customer"] + base["offer_cost_per_customer"])
    table["base_expected_prevented_churn"] = table["predicted_probability"] * effectiveness
    table["base_expected_gross_retained_contribution"] = (
        table["predicted_probability"]
        * effectiveness
        * table["monthly_charges"]
        * horizon
        * margin
    )
    table["base_cost_if_contacted"] = cost
    table["base_net_expected_value_if_contacted"] = (
        table["base_expected_gross_retained_contribution"] - cost
    )
    return table.sort_values("risk_rank", kind="mergesort").reset_index(drop=True)


def assumptions_table(config: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for scenario in config["scenarios"]:
        rows.append(
            {
                **scenario,
                "currency_unit": config["currency_unit"],
                "effectiveness_definition": config["effectiveness_definition"],
                "offer_cost_incidence": config["offer_cost_incidence"],
                "assumption_status": "illustrative; not empirically validated",
            }
        )
    return pd.DataFrame(rows)


def build_outputs(
    database_path: Path, phase3a_dir: Path, config_path: Path
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    config = load_config(config_path)
    customers, source_hashes = load_frozen_test_customers(database_path, phase3a_dir)
    capacities = [float(value) for value in config["capacities"]]
    scenarios = config["scenarios"]
    base = next(item for item in scenarios if item["name"] == "base")
    scenario_outcomes, break_even = scenario_tables(customers, capacities, scenarios)
    tables = {
        "capacity_performance": capacity_performance(customers, capacities),
        "scenario_assumptions": assumptions_table(config),
        "scenario_outcomes": scenario_outcomes,
        "break_even": break_even,
        "sensitivity_analysis": sensitivity_table(
            customers, capacities, base, config["sensitivity"]
        ),
        "customer_targeting": customer_targeting_table(customers, capacities, base),
    }
    manifest = {
        "artifact_version": config["artifact_version"],
        "source_phase3a_directory": str(phase3a_dir.resolve()),
        "source_phase3a_hashes": source_hashes,
        "source_prediction_rows": len(customers),
        "source_churned_rows": int(customers["actual_churn"].sum()),
        "capacities": capacities,
        "ranking_rule": "Descending frozen predicted probability; customer_id ascending breaks ties.",
        "individual_selection_uses_actual_churn": False,
        "actual_churn_usage": "Aggregate retrospective capacity evaluation only.",
        "currency_unit": config["currency_unit"],
        "effectiveness_definition": config["effectiveness_definition"],
        "offer_cost_incidence": config["offer_cost_incidence"],
        "formulas": {
            "contacted_count": "ceil(capacity_fraction * test_customer_count)",
            "expected_prevented_churn": "sum(predicted_probability * relative_risk_reduction)",
            "gross_expected_retained_contribution": "sum(predicted_probability * relative_risk_reduction * monthly_charges * benefit_horizon_months * contribution_margin_rate)",
            "total_campaign_cost": "contacted_count * (contact_cost_per_customer + offer_cost_per_customer)",
            "net_expected_scenario_value": "gross_expected_retained_contribution - total_campaign_cost",
            "break_even_effectiveness": "total_campaign_cost / sum(predicted_probability * monthly_charges * benefit_horizon_months * contribution_margin_rate)",
        },
    }
    return tables, manifest


def run_analysis(
    database_path: Path,
    phase3a_dir: Path,
    config_path: Path,
    output_root: Path,
    version: str,
) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise ValueError("Output version may contain only letters, numbers, dot, underscore, and dash")
    target_dir = output_root.resolve() / version
    if target_dir.exists():
        raise FileExistsError(f"Output version already exists: {target_dir}")
    output_root.mkdir(parents=True, exist_ok=True)
    tables, manifest = build_outputs(
        database_path.resolve(), phase3a_dir.resolve(), config_path.resolve()
    )

    with tempfile.TemporaryDirectory(prefix=f".{version}-", dir=output_root.resolve()) as staging:
        staging_dir = Path(staging)
        for name, table in tables.items():
            table.to_csv(
                staging_dir / f"{name}_{version}.csv",
                index=False,
                float_format="%.15g",
            )
        _write_json(staging_dir / f"run_manifest_{version}.json", manifest)
        hashes = {
            path.name: sha256_file(path)
            for path in sorted(staging_dir.iterdir())
            if path.is_file()
        }
        _write_json(staging_dir / f"output_hashes_{version}.json", hashes)
        staging_dir.rename(target_dir)

    print(f"Power BI-ready outputs: {target_dir}")
    for name, table in tables.items():
        print(f"{name}: {len(table)} rows")
    return target_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--phase3a-dir", type=Path, default=DEFAULT_PHASE3A)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--version", default="v1")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_analysis(args.database, args.phase3a_dir, args.config, args.output_root, args.version)


if __name__ == "__main__":
    main()
