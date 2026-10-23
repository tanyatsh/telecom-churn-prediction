"""Static PBIP/TMDL checks and independent scenario-measure reconciliation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PBIP_ROOT = PROJECT_ROOT / "powerbi"
DEFAULT_MODEL_ROOT = DEFAULT_PBIP_ROOT / "TelecomChurn.SemanticModel"
DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "phase5a"
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "retention_scenarios_v1.json"
DEFAULT_PHASE4A = PROJECT_ROOT / "outputs" / "powerbi" / "phase4a" / "v1"

PBIP_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/pbip/"
    "pbipProperties/1.0.0/schema.json"
)
PBIR_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/"
    "definitionProperties/2.0.0/schema.json"
)

SOURCE_TABLES = {
    "KPIOverallChurn": ("outputs/eda/overall_summary.csv", 1, []),
    "AggChurnByContract": ("outputs/eda/churn_by_contract.csv", 3, ["contract"]),
    "AggChurnByTenureBand": ("outputs/eda/churn_by_tenure_band.csv", 6, ["tenure_band"]),
    "AggChurnByInternetService": ("outputs/eda/churn_by_internet_service.csv", 3, ["internet_service"]),
    "AggChurnByPaymentMethod": ("outputs/eda/churn_by_payment_method.csv", 4, ["payment_method"]),
    "AggChurnByMonthlyChargeBand": ("outputs/eda/churn_by_monthly_charge_band.csv", 4, ["monthly_charge_band"]),
    "KPIModelTest": ("artifacts/phase3a/v1/test_metrics_v1.json", 1, []),
    "ModelComparison": ("artifacts/phase3a/v1/model_comparison_v1.csv", 3, ["model"]),
    "CalibrationDecile": ("artifacts/phase3a/v1/calibration_v1.csv", 10, ["calibration_decile"]),
    "ConfusionMatrix": ("artifacts/phase3a/v1/confusion_matrix_v1.csv", 2, ["actual_class"]),
    "PermutationImportance": ("artifacts/phase3b/v1/permutation_importance_v1.csv", 18, ["feature"]),
    "SubgroupPerformance": ("artifacts/phase3b/v1/subgroup_performance_v1.csv", 11, ["dimension", "group"]),
    "RiskDecile": ("artifacts/phase3b/v1/risk_deciles_v1.csv", 10, ["calibration_decile"]),
    "DimCapacity": ("outputs/powerbi/phase4a/v1/capacity_performance_v1.csv", 3, ["capacity_fraction"]),
    "DimScenario": ("outputs/powerbi/phase4a/v1/scenario_assumptions_v1.csv", 3, ["name"]),
    "FactScenarioOutcome": ("outputs/powerbi/phase4a/v1/scenario_outcomes_v1.csv", 9, ["scenario", "capacity_fraction"]),
    "FactBreakEven": ("outputs/powerbi/phase4a/v1/break_even_v1.csv", 9, ["scenario", "capacity_fraction"]),
    "FactSensitivity": ("outputs/powerbi/phase4a/v1/sensitivity_analysis_v1.csv", 66, ["varied_parameter", "varied_value", "capacity_fraction"]),
    "FactTargetCustomer": ("outputs/powerbi/phase4a/v1/customer_targeting_v1.csv", 1_409, ["customer_id"]),
}

PARAMETER_TABLES = {
    "pCapacity",
    "pBenefitHorizon",
    "pMargin",
    "pEffectiveness",
    "pContactCost",
    "pOfferCost",
}

EXPECTED_REPORT_PAGES = {
    "c29817541de24331942e": 11,
    "d7f3a6b42c1e4f7890ab": 11,
    "a41c9e7b5d2f4386bc10": 17,
}

PAGE3_ID = "a41c9e7b5d2f4386bc10"
PAGE3_SLICER_DEFAULTS = {
    "20000000000000000003": ("pCapacity", "0.2D", "0%"),
    "20000000000000000004": ("pEffectiveness", "0.2D", "0%"),
    "20000000000000000005": ("pMargin", "0.55D", "0%"),
    "20000000000000000006": ("pBenefitHorizon", "6L", "#,##0"),
    "20000000000000000007": ("pContactCost", "5L", "#,##0"),
    "20000000000000000008": ("pOfferCost", "5L", "#,##0"),
}
PAGE3_DYNAMIC_KPIS = {
    "20000000000000000009": ("Net Expected Scenario Value Dynamic", "#,##0"),
    "20000000000000000010": (
        "Gross Expected Retained Contribution Dynamic",
        "#,##0",
    ),
    "20000000000000000011": ("Campaign Cost Dynamic", "#,##0"),
    "20000000000000000012": ("Contacted Customers Dynamic", "#,##0"),
    "20000000000000000013": ("Expected Prevented Churn Dynamic", "0.0"),
    "20000000000000000014": ("Break-Even Effectiveness Dynamic", "0.0%"),
}
PAGE3_TARGETING_COLUMNS = {
    "capacity_label": "",
    "contacted_customers": "#,##0",
    "observed_churn_capture": "0.0%",
    "precision": "0.0%",
    "lift": "0.000",
}

EXPECTED_RELATIONSHIPS = {
    "rel_ScenarioOutcome_Capacity": ("FactScenarioOutcome.capacity_fraction", "DimCapacity.capacity_fraction"),
    "rel_BreakEven_Capacity": ("FactBreakEven.capacity_fraction", "DimCapacity.capacity_fraction"),
    "rel_Sensitivity_Capacity": ("FactSensitivity.capacity_fraction", "DimCapacity.capacity_fraction"),
    "rel_ScenarioOutcome_Scenario": ("FactScenarioOutcome.scenario", "DimScenario.name"),
    "rel_BreakEven_Scenario": ("FactBreakEven.scenario", "DimScenario.name"),
}

EXPECTED_MEASURES = {
    "KPIOverallChurn": {
        "Descriptive Customer Count",
        "Descriptive Churned Customers",
        "Descriptive Retained Customers",
        "Descriptive Churn Rate",
        "Blank TotalCharges Count",
        "Descriptive Population Label",
    },
    "KPIModelTest": {
        "Held-out Test Customer Count",
        "Test Churned Customers",
        "Test Prevalence",
        "ROC-AUC",
        "PR-AUC",
        "PR-AUC Baseline",
        "ROC-AUC Baseline",
        "Brier Score",
        "Log Loss",
        "Calibration Error (ECE)",
        "Illustrative Threshold",
        "Recall at Top 20%",
        "Precision at Top 20%",
        "Lift at Top 20%",
        "Confusion TN",
        "Confusion FP",
        "Confusion FN",
        "Confusion TP",
        "Test Population Label",
    },
    "DimCapacity": {
        "Fixed Contacted Customers",
        "Fixed Observed Churn Capture",
        "Fixed Capacity Precision",
        "Fixed Capacity Lift",
    },
    "FactScenarioOutcome": {
        "Static Scenario Net Expected Value",
        "Static Expected Prevented Churn",
        "Static Break-Even Effectiveness",
    },
    "FactTargetCustomer": {
        "Selected Capacity",
        "Selected Horizon Months",
        "Selected Margin",
        "Selected Effectiveness",
        "Selected Contact Cost",
        "Selected Offer Cost",
        "Valid Scenario Inputs",
        "Scenario Input Status",
        "Contacted Customers Dynamic",
        "Predicted Churn Sum Dynamic",
        "Expected Prevented Churn Dynamic",
        "Full-Effect Contribution Dynamic",
        "Gross Expected Retained Contribution Dynamic",
        "Campaign Cost Dynamic",
        "Net Expected Scenario Value Dynamic",
        "Break-Even Effectiveness Dynamic",
        "Net Expected Value Per Contact Dynamic",
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _object_name(line: str, kind: str) -> str:
    raw = line.split(kind, 1)[1].strip()
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("''", "'")
    return raw


def parse_table_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    table_line = next((line for line in lines if line.startswith("table ")), None)
    if table_line is None:
        raise ValueError(f"Missing table declaration: {path}")
    table = _object_name(table_line, "table ")
    columns: dict[str, dict[str, Any]] = {}
    measures: list[str] = []
    for index, line in enumerate(lines):
        if line.startswith("\tcolumn "):
            name = _object_name(line.strip(), "column ")
            block: list[str] = []
            for following in lines[index + 1 :]:
                if following.startswith("\t") and not following.startswith("\t\t"):
                    break
                block.append(following)
            joined = "\n".join(block)
            data_type = re.search(r"^\t\tdataType:\s*(\S+)", joined, re.MULTILINE)
            source_column = re.search(r"^\t\tsourceColumn:\s*(.+)$", joined, re.MULTILINE)
            columns[name] = {
                "data_type": data_type.group(1) if data_type else None,
                "source_column": source_column.group(1).strip() if source_column else None,
                "is_key": bool(re.search(r"^\t\tisKey\s*$", joined, re.MULTILINE)),
            }
        elif line.startswith("\tmeasure "):
            declaration = line.strip().split(" =", 1)[0]
            measures.append(_object_name(declaration, "measure "))
            previous = next((candidate for candidate in reversed(lines[:index]) if candidate.strip()), "")
            if not previous.strip().startswith("///"):
                raise ValueError(f"Undocumented measure {table}[{measures[-1]}]")
    return {"table": table, "columns": columns, "measures": measures, "text": text}


def validate_project_shell(pbip_root: Path, model_root: Path) -> dict[str, Any]:
    pbip_path = pbip_root / "TelecomChurn.pbip"
    report_path = pbip_root / "TelecomChurn.Report" / "definition.pbir"
    pbism_path = model_root / "definition.pbism"
    for required in [pbip_path, report_path, pbism_path, model_root / "definition" / "database.tmdl", model_root / "definition" / "model.tmdl", model_root / "definition" / "expressions.tmdl", model_root / "definition" / "relationships.tmdl"]:
        if not required.is_file():
            raise ValueError(f"Missing required PBIP/TMDL file: {required}")
    pbip = json.loads(pbip_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    pbism = json.loads(pbism_path.read_text(encoding="utf-8"))
    if pbip.get("$schema") != PBIP_SCHEMA:
        raise ValueError("PBIP project shortcut has an invalid or missing $schema")
    if report.get("$schema") != PBIR_SCHEMA:
        raise ValueError("PBIR report definition has an invalid or missing $schema")
    if pbip["artifacts"][0]["report"]["path"] != "TelecomChurn.Report":
        raise ValueError("PBIP report path is not portable and relative")
    if report["datasetReference"]["byPath"]["path"] != "../TelecomChurn.SemanticModel":
        raise ValueError("Report semantic-model reference is not portable and relative")
    if float(pbism["version"]) < 4.0:
        raise ValueError("definition.pbism version does not support TMDL")
    pages_root = pbip_root / "TelecomChurn.Report" / "definition" / "pages"
    pages_metadata_path = pages_root / "pages.json"
    if not pages_metadata_path.is_file():
        raise ValueError("Report pages metadata is missing")
    pages_metadata = json.loads(pages_metadata_path.read_text(encoding="utf-8"))
    expected_page_order = list(EXPECTED_REPORT_PAGES)
    if pages_metadata.get("pageOrder") != expected_page_order:
        raise ValueError(
            f"Report page order mismatch: {pages_metadata.get('pageOrder')}"
        )
    if pages_metadata.get("activePageName") != expected_page_order[0]:
        raise ValueError("Executive Churn Overview must remain the active first page")
    discovered_pages = {
        path.parent.name
        for path in pages_root.glob("*/page.json")
    }
    if discovered_pages != set(EXPECTED_REPORT_PAGES):
        raise ValueError(
            f"Report page inventory mismatch: {discovered_pages ^ set(EXPECTED_REPORT_PAGES)}"
        )
    report_visuals = 0
    for page_name, expected_visuals in EXPECTED_REPORT_PAGES.items():
        page_path = pages_root / page_name / "page.json"
        page = json.loads(page_path.read_text(encoding="utf-8"))
        if page.get("name") != page_name:
            raise ValueError(f"Page identity mismatch in {page_path}")
        if page.get("width") != 1280 or page.get("height") != 720:
            raise ValueError(f"Page {page_name} must use the 1280x720 canvas")
        visual_files = list((page_path.parent / "visuals").glob("*/visual.json"))
        if len(visual_files) != expected_visuals:
            raise ValueError(
                f"Page {page_name} visual count {len(visual_files)} != {expected_visuals}"
            )
        report_visuals += len(visual_files)
    page3 = validate_page3_report_design(pages_root / PAGE3_ID, model_root)
    database_text = (model_root / "definition" / "database.tmdl").read_text(encoding="utf-8")
    model_text = (model_root / "definition" / "model.tmdl").read_text(encoding="utf-8")
    if "compatibilityLevel: 1702" not in database_text:
        raise ValueError("Database compatibility level is incomplete")
    compatibility_mode = re.search(
        r"^\s*compatibilityMode:\s*(\S+)", database_text, re.MULTILINE
    )
    if compatibility_mode and compatibility_mode.group(1) != "powerBI":
        raise ValueError("Explicit database compatibility mode must be powerBI")
    if "defaultPowerBIDataSourceVersion: powerBI_V3" not in model_text:
        raise ValueError("Import model must use Power BI V3 data source metadata")
    if "discourageImplicitMeasures" not in model_text:
        raise ValueError("Implicit measures must be discouraged")
    return {
        "pbip": pbip_path.name,
        "report_pages": len(discovered_pages),
        "report_visuals": report_visuals,
        "page3": page3,
        "pbism_version": pbism["version"],
    }


def _literal_value(properties: dict[str, Any], name: str) -> str:
    return properties[name]["expr"]["Literal"]["Value"]


def validate_page3_report_design(
    page_root: Path, model_root: Path = DEFAULT_MODEL_ROOT
) -> dict[str, Any]:
    """Validate Page 3 bindings, persisted defaults, and layout boundaries."""
    page = json.loads((page_root / "page.json").read_text(encoding="utf-8"))
    if page.get("displayName") != "Retention Strategy & Scenario Simulator":
        raise ValueError("Page 3 display name does not match the approved specification")
    if page.get("width") != 1280 or page.get("height") != 720:
        raise ValueError("Page 3 must use the 1280x720 canvas")

    visual_paths = sorted((page_root / "visuals").glob("*/visual.json"))
    visuals = {
        path.parent.name: json.loads(path.read_text(encoding="utf-8"))
        for path in visual_paths
    }
    if set(visuals) != {
        f"200000000000000000{number:02d}" for number in range(1, 18)
    }:
        raise ValueError("Page 3 visual inventory does not match the approved 17 visuals")

    for visual_id, payload in visuals.items():
        if payload.get("name") != visual_id:
            raise ValueError(f"Page 3 visual identity mismatch: {visual_id}")
        position = payload["position"]
        if (
            position["x"] < 0
            or position["y"] < 0
            or position["x"] + position["width"] > 1280
            or position["y"] + position["height"] > 720
        ):
            raise ValueError(f"Page 3 visual exceeds layout bounds: {visual_id}")

    for visual_id, (table, default_literal, expected_format) in PAGE3_SLICER_DEFAULTS.items():
        payload = visuals[visual_id]
        visual = payload["visual"]
        if visual.get("visualType") != "slicer":
            raise ValueError(f"Page 3 parameter visual is not a slicer: {visual_id}")
        if payload.get("howCreated") != "WhatIfParameterControl":
            raise ValueError(f"Page 3 slicer lacks what-if provenance: {visual_id}")
        projection = visual["query"]["queryState"]["Values"]["projections"]
        if len(projection) != 1:
            raise ValueError(f"Page 3 slicer must bind one field: {visual_id}")
        projection = projection[0]
        column = projection["field"]["Column"]
        if (
            column["Expression"]["SourceRef"].get("Entity") != table
            or column.get("Property") != "Value"
            or projection.get("format") != expected_format
        ):
            raise ValueError(f"Page 3 slicer field binding mismatch: {visual_id}")

        objects = visual["objects"]
        selection = objects["selection"][0]["properties"]
        if (
            _literal_value(selection, "selectAllCheckboxEnabled") != "false"
            or _literal_value(selection, "singleSelect") != "true"
            or _literal_value(selection, "strictSingleSelect") != "true"
        ):
            raise ValueError(f"Page 3 slicer is not strict single-select: {visual_id}")
        if _literal_value(objects["data"][0]["properties"], "mode") != "'Dropdown'":
            raise ValueError(f"Page 3 slicer is not configured as a dropdown: {visual_id}")

        saved_filter = objects["general"][0]["properties"]["filter"]["filter"]
        if saved_filter.get("Version") != 2 or len(saved_filter.get("From", [])) != 1:
            raise ValueError(f"Page 3 slicer default filter is malformed: {visual_id}")
        source = saved_filter["From"][0]
        where = saved_filter["Where"]
        if source.get("Entity") != table or len(where) != 1:
            raise ValueError(f"Page 3 slicer default source mismatch: {visual_id}")
        condition = where[0]["Condition"]["In"]
        selected_column = condition["Expressions"][0]["Column"]
        values = condition["Values"]
        if (
            selected_column["Expression"]["SourceRef"].get("Source") != source["Name"]
            or selected_column.get("Property") != "Value"
            or values != [[{"Literal": {"Value": default_literal}}]]
        ):
            raise ValueError(f"Page 3 slicer default value mismatch: {visual_id}")
        if "filterConfig" in payload:
            raise ValueError(
                f"Page 3 slicer selection must use objects.general.filter: {visual_id}"
            )

    for visual_id, (measure, expected_format) in PAGE3_DYNAMIC_KPIS.items():
        payload = visuals[visual_id]
        visual = payload["visual"]
        if visual.get("visualType") != "cardVisual":
            raise ValueError(f"Page 3 dynamic output is not a card: {visual_id}")
        projections = visual["query"]["queryState"]["Data"]["projections"]
        if len(projections) != 1:
            raise ValueError(f"Page 3 dynamic card must bind one measure: {visual_id}")
        projection = projections[0]
        measure_ref = projection["field"]["Measure"]
        if (
            measure_ref["Expression"]["SourceRef"].get("Entity")
            != "FactTargetCustomer"
            or measure_ref.get("Property") != measure
            or projection.get("format") != expected_format
        ):
            raise ValueError(f"Page 3 dynamic KPI binding mismatch: {visual_id}")
        if "actual_churn" in json.dumps(payload).lower():
            raise ValueError(f"Page 3 dynamic KPI references actual churn: {visual_id}")

    targeting = visuals["20000000000000000015"]["visual"]
    if targeting.get("visualType") != "tableEx":
        raise ValueError("Page 3 targeting comparison must be a native table")
    targeting_projections = targeting["query"]["queryState"]["Values"]["projections"]
    actual_targeting = {}
    for projection in targeting_projections:
        column = projection["field"]["Column"]
        if column["Expression"]["SourceRef"].get("Entity") != "DimCapacity":
            raise ValueError("Page 3 targeting comparison uses an unapproved table")
        actual_targeting[column["Property"]] = projection.get("format", "")
    if actual_targeting != PAGE3_TARGETING_COLUMNS:
        raise ValueError(
            f"Page 3 targeting comparison contract mismatch: {actual_targeting}"
        )

    target_text = (
        model_root / "definition" / "tables" / "FactTargetCustomer.tmdl"
    ).read_text(encoding="utf-8")
    dax_defaults = [
        "SELECTEDVALUE(pCapacity[Value], 0.20)",
        "SELECTEDVALUE(pEffectiveness[Value], 0.20)",
        "SELECTEDVALUE(pMargin[Value], 0.55)",
        "SELECTEDVALUE(pBenefitHorizon[Value], 6)",
        "SELECTEDVALUE(pContactCost[Value], 5)",
        "SELECTEDVALUE(pOfferCost[Value], 5)",
    ]
    for token in dax_defaults:
        if token not in target_text:
            raise ValueError(f"Page 3 DAX fallback default is missing: {token}")

    return {
        "visuals": len(visuals),
        "slicers": len(PAGE3_SLICER_DEFAULTS),
        "dynamic_kpis": len(PAGE3_DYNAMIC_KPIS),
        "targeting_capacity_rows": 3,
        "layout_bounds": "PASS",
        "persisted_defaults": "PASS",
    }


def validate_tables(model_root: Path) -> tuple[dict[str, dict[str, Any]], pd.DataFrame]:
    table_paths = sorted((model_root / "definition" / "tables").glob("*.tmdl"))
    parsed = {item["table"]: item for item in (parse_table_file(path) for path in table_paths)}
    expected_tables = set(SOURCE_TABLES) | PARAMETER_TABLES
    if set(parsed) != expected_tables:
        raise ValueError(f"TMDL table inventory mismatch: {set(parsed) ^ expected_tables}")
    model_text = (model_root / "definition" / "model.tmdl").read_text(encoding="utf-8")
    refs = set(re.findall(r"^ref table (.+)$", model_text, re.MULTILINE))
    if refs != expected_tables:
        raise ValueError(f"model.tmdl table references mismatch: {refs ^ expected_tables}")

    rows = []
    for table, (relative, expected_rows, keys) in SOURCE_TABLES.items():
        definition = parsed[table]
        normalized = relative.replace("/", "\\")
        if normalized not in definition["text"]:
            raise ValueError(f"{table} does not reference approved relative source {relative}")
        if "partition " not in definition["text"] or " = m" not in definition["text"]:
            raise ValueError(f"{table} must use an import M partition")
        source_path = PROJECT_ROOT / Path(relative)
        if not source_path.is_file():
            raise ValueError(f"Missing source for {table}: {relative}")
        if source_path.suffix.lower() == ".csv":
            frame = pd.read_csv(source_path)
            if len(frame) != expected_rows:
                raise ValueError(f"{table} source row count {len(frame)} != {expected_rows}")
            if keys and (frame[keys].isna().any().any() or frame.duplicated(keys).any()):
                raise ValueError(f"{table} source key failed: {keys}")
            defined_sources = {metadata["source_column"] for metadata in definition["columns"].values()}
            for column in frame.columns:
                if column not in defined_sources:
                    raise ValueError(f"{table}.{column} lacks a TMDL sourceColumn mapping")
        for column, metadata in definition["columns"].items():
            if metadata["data_type"] is None or metadata["source_column"] is None:
                raise ValueError(f"{table}.{column} lacks dataType or sourceColumn")
        rows.append({"table": table, "source": relative, "rows": expected_rows, "key": " + ".join(keys) or "single row", "status": "PASS"})

    for table in PARAMETER_TABLES:
        definition = parsed[table]
        if " = calculated" not in definition["text"]:
            raise ValueError(f"Disconnected parameter {table} must be a calculated table")
        if set(definition["columns"]) != {"Value"}:
            raise ValueError(f"Disconnected parameter {table} must expose only Value")
    return parsed, pd.DataFrame(rows)


def validate_relationship_metadata(text: str) -> None:
    if re.search(r"^\s*description\s*:", text, re.MULTILINE | re.IGNORECASE):
        raise ValueError(
            "Single-column relationships do not support a relationship-level description property"
        )
    if re.search(r"^[ \t]*///", text, re.MULTILINE):
        raise ValueError(
            "TMDL /// documentation on a relationship is emitted as unsupported description metadata"
        )


def validate_relationships(model_root: Path) -> dict[str, tuple[str, str]]:
    text = (model_root / "definition" / "relationships.tmdl").read_text(encoding="utf-8")
    validate_relationship_metadata(text)
    blocks = re.split(r"(?=^relationship )", text, flags=re.MULTILINE)
    actual: dict[str, tuple[str, str]] = {}
    for block in blocks:
        if not block.startswith("relationship "):
            continue
        name = block.splitlines()[0].split("relationship ", 1)[1].strip().strip("'")
        from_match = re.search(r"^\tfromColumn:\s*(.+)$", block, re.MULTILINE)
        to_match = re.search(r"^\ttoColumn:\s*(.+)$", block, re.MULTILINE)
        if not from_match or not to_match:
            raise ValueError(f"Relationship {name} lacks endpoints")
        from_cardinality = re.search(
            r"^\tfromCardinality:\s*(\S+)", block, re.MULTILINE
        )
        to_cardinality = re.search(
            r"^\ttoCardinality:\s*(\S+)", block, re.MULTILINE
        )
        filter_direction = re.search(
            r"^\tcrossFilteringBehavior:\s*(\S+)", block, re.MULTILINE
        )
        if from_cardinality and from_cardinality.group(1) != "many":
            raise ValueError(f"Relationship {name} from-cardinality is not many")
        if to_cardinality and to_cardinality.group(1) != "one":
            raise ValueError(f"Relationship {name} to-cardinality is not one")
        if filter_direction and filter_direction.group(1) != "oneDirection":
            raise ValueError(f"Relationship {name} is not single-direction")
        actual[name] = (from_match.group(1).strip(), to_match.group(1).strip())
    if actual != EXPECTED_RELATIONSHIPS:
        raise ValueError(f"Relationship contract mismatch: {actual}")
    forbidden = {"FactTargetCustomer"} | PARAMETER_TABLES
    if any(item in text for item in forbidden):
        raise ValueError("Customer targeting and parameter tables must remain disconnected")
    return actual


def validate_measure_expression_boundaries(text: str, source: str = "TMDL") -> list[str]:
    """Validate indentation boundaries for non-fenced multiline measure DAX."""
    lines = text.splitlines()
    multiline_measures: list[str] = []
    declaration = re.compile(r"^(\t*)measure\s+(.+?)\s*=\s*$")
    metadata = re.compile(r"^(?:formatString|displayFolder)\s*:", re.IGNORECASE)

    for index, line in enumerate(lines):
        match = declaration.match(line)
        if not match:
            continue
        measure_name = _object_name(f"measure {match.group(2)}", "measure ")
        multiline_measures.append(measure_name)
        object_indent = len(match.group(1))
        property_indent = object_indent + 1
        expression_indent = object_indent + 2
        expression_found = False

        for following in lines[index + 1 :]:
            if not following.strip():
                continue
            leading_tabs = len(following) - len(following.lstrip("\t"))
            stripped = following.lstrip("\t")
            if leading_tabs <= object_indent:
                break
            if leading_tabs == property_indent:
                if not expression_found:
                    raise ValueError(
                        f"{source}: multiline measure {measure_name!r} DAX must be indented "
                        "one level deeper than its properties"
                    )
                break
            if leading_tabs < expression_indent:
                raise ValueError(f"{source}: invalid indentation in multiline measure {measure_name!r}")
            if metadata.match(stripped):
                raise ValueError(
                    f"{source}: {stripped.split(':', 1)[0]} is indented inside the DAX "
                    f"expression for measure {measure_name!r}"
                )
            expression_found = True

        if not expression_found:
            raise ValueError(f"{source}: multiline measure {measure_name!r} has no DAX expression")

    return multiline_measures


def validate_measures(parsed: dict[str, dict[str, Any]]) -> pd.DataFrame:
    actual = {table: set(definition["measures"]) for table, definition in parsed.items() if definition["measures"]}
    if actual != EXPECTED_MEASURES:
        raise ValueError(f"Measure inventory mismatch: {actual}")
    for table, definition in parsed.items():
        validate_measure_expression_boundaries(definition["text"], f"{table}.tmdl")
    target_text = parsed["FactTargetCustomer"]["text"]
    if "actual_churn" in target_text.lower():
        raise ValueError("Dynamic scenario model must not reference actual churn labels")
    required_dynamic_tokens = [
        "ALL(FactTargetCustomer)",
        "FactTargetCustomer[predicted_probability]",
        "FactTargetCustomer[monthly_charges]",
        "FactTargetCustomer[risk_rank]",
        "[Selected Effectiveness]",
        "[Selected Horizon Months]",
        "[Selected Margin]",
        "[Selected Contact Cost]",
        "[Selected Offer Cost]",
    ]
    for token in required_dynamic_tokens:
        if token not in target_text:
            raise ValueError(f"Dynamic DAX is missing required token: {token}")
    return pd.DataFrame(
        [{"table": table, "measure": measure} for table in sorted(actual) for measure in sorted(actual[table])]
    )


def validate_paths(pbip_root: Path) -> dict[str, Any]:
    pending_changes = list(pbip_root.rglob("unappliedChanges.json"))
    if pending_changes:
        relative = [str(path.relative_to(PROJECT_ROOT)) for path in pending_changes]
        raise ValueError(f"Unresolved Power Query changes are present: {relative}")

    git_files = subprocess.run(
        [
            "git",
            "-C",
            str(PROJECT_ROOT),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    files = [
        PROJECT_ROOT / relative
        for relative in git_files
        if relative and (PROJECT_ROOT / relative).is_file()
    ]
    forbidden_suffixes = {".abf", ".csv", ".duckdb", ".joblib", ".parquet", ".pickle", ".pkl"}
    forbidden_publishable = [
        str(path.relative_to(PROJECT_ROOT))
        for path in files
        if path.suffix.lower() in forbidden_suffixes
        or path.name.lower() == "localsettings.json"
    ]
    if forbidden_publishable:
        raise ValueError(
            "Generated data, model binaries, or local caches are eligible for publication: "
            f"{forbidden_publishable}"
        )

    personal = re.compile(r"[A-Za-z]:[\\/](?:Users|Documents)[\\/]", re.IGNORECASE)
    violations = []
    text_files_scanned = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        text_files_scanned += 1
        if personal.search(text):
            violations.append(str(path.relative_to(PROJECT_ROOT)))
    if violations:
        raise ValueError(f"PBIP contains personal absolute paths: {violations}")
    expression_text = (DEFAULT_MODEL_ROOT / "definition" / "expressions.tmdl").read_text(encoding="utf-8")
    if 'expression DataRoot = "<SET_PROJECT_ROOT>"' not in expression_text:
        raise ValueError("DataRoot must use the neutral placeholder")
    if "File.Contents" not in expression_text:
        raise ValueError("LoadCsv must resolve local files through DataRoot")
    return {
        "publishable_files": len(files),
        "text_files_scanned": text_files_scanned,
        "personal_absolute_path_violations": 0,
        "forbidden_publishable_files": [],
        "unapplied_query_changes": 0,
        "data_root_placeholder": "<SET_PROJECT_ROOT>",
    }


def reconcile_scenario_measures(config_path: Path, phase4a_dir: Path) -> pd.DataFrame:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    customers = pd.read_csv(phase4a_dir / "customer_targeting_v1.csv").sort_values("risk_rank", kind="mergesort")
    outcomes = pd.read_csv(phase4a_dir / "scenario_outcomes_v1.csv")
    rows = []
    for scenario in config["scenarios"]:
        for capacity in config["capacities"]:
            count = math.ceil(capacity * len(customers))
            selected = customers.iloc[:count]
            predicted_sum = float(selected["predicted_probability"].sum())
            full_effect = float(
                (
                    selected["predicted_probability"]
                    * selected["monthly_charges"]
                    * scenario["benefit_horizon_months"]
                    * scenario["contribution_margin_rate"]
                ).sum()
            )
            expected_prevented = predicted_sum * scenario["relative_risk_reduction"]
            gross = full_effect * scenario["relative_risk_reduction"]
            campaign_cost = count * (
                scenario["contact_cost_per_customer"] + scenario["offer_cost_per_customer"]
            )
            net = gross - campaign_cost
            break_even = campaign_cost / full_effect
            exported = outcomes.loc[
                (outcomes["scenario"] == scenario["name"])
                & outcomes["capacity_fraction"].map(lambda value: math.isclose(value, capacity, abs_tol=1e-12))
            ].iloc[0]
            checks = {
                "contacted_customers": (count, exported["contacted_customers"]),
                "predicted_churn_sum_contacted": (predicted_sum, exported["predicted_churn_sum_contacted"]),
                "expected_prevented_churn": (expected_prevented, exported["expected_prevented_churn"]),
                "probability_weighted_contribution_at_full_effect": (full_effect, exported["probability_weighted_contribution_at_full_effect"]),
                "gross_expected_retained_contribution": (gross, exported["gross_expected_retained_contribution"]),
                "total_campaign_cost": (campaign_cost, exported["total_campaign_cost"]),
                "net_expected_scenario_value": (net, exported["net_expected_scenario_value"]),
                "break_even_effectiveness": (break_even, exported["break_even_effectiveness"]),
            }
            for metric, (calculated, expected) in checks.items():
                if not math.isclose(float(calculated), float(expected), rel_tol=1e-12, abs_tol=1e-9):
                    raise ValueError(f"Scenario measure mismatch {scenario['name']} {capacity} {metric}: {calculated} != {expected}")
            rows.append(
                {
                    "scenario": scenario["name"],
                    "capacity_fraction": capacity,
                    "contacted_customers": count,
                    "calculated_net_expected_value": net,
                    "exported_net_expected_value": float(exported["net_expected_scenario_value"]),
                    "calculated_break_even_effectiveness": break_even,
                    "exported_break_even_effectiveness": float(exported["break_even_effectiveness"]),
                    "is_default_base_20pct": scenario["name"] == "base" and math.isclose(capacity, 0.20),
                    "status": "PASS",
                }
            )
    return pd.DataFrame(rows)


def run_validation(
    pbip_root: Path,
    model_root: Path,
    config_path: Path,
    phase4a_dir: Path,
    artifact_root: Path,
    version: str,
) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise ValueError("Version contains invalid characters")
    target = artifact_root.resolve() / version
    if target.exists():
        raise FileExistsError(f"Validation artifact version already exists: {target}")
    shell = validate_project_shell(pbip_root.resolve(), model_root.resolve())
    parsed, table_contract = validate_tables(model_root.resolve())
    relationships = validate_relationships(model_root.resolve())
    measures = validate_measures(parsed)
    portability = validate_paths(pbip_root.resolve())
    scenarios = reconcile_scenario_measures(config_path.resolve(), phase4a_dir.resolve())
    default_row = scenarios.loc[scenarios["is_default_base_20pct"]].iloc[0]
    summary = {
        "status": "PASS",
        "pbip": shell,
        "imported_tables_validated": len(SOURCE_TABLES),
        "calculated_parameter_tables_validated": len(PARAMETER_TABLES),
        "relationships_validated": len(relationships),
        "measures_validated": len(measures),
        "scenario_measure_rows_reconciled": len(scenarios),
        "descriptive_population_customers": 7_043,
        "held_out_test_customers": 1_409,
        "default_scenario": {
            "scenario": "base",
            "capacity_fraction": 0.20,
            "contacted_customers": int(default_row["contacted_customers"]),
            "net_expected_scenario_value": float(default_row["calculated_net_expected_value"]),
            "break_even_effectiveness": float(default_row["calculated_break_even_effectiveness"]),
        },
        "portability": portability,
        "tmdl_validation_scope": "static structural checks; Power BI Desktop must perform authoritative TMDL deserialization and refresh",
    }
    artifact_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{version}-", dir=artifact_root.resolve()) as staging:
        stage = Path(staging)
        table_contract.to_csv(stage / f"table_contract_{version}.csv", index=False)
        measures.to_csv(stage / f"measure_inventory_{version}.csv", index=False)
        scenarios.to_csv(stage / f"scenario_measure_reconciliation_{version}.csv", index=False)
        _write_json(stage / f"model_validation_summary_{version}.json", summary)
        hashes = {path.name: sha256_file(path) for path in stage.iterdir() if path.is_file()}
        _write_json(stage / f"artifact_hashes_{version}.json", hashes)
        stage.rename(target)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"Validation artifacts: {target}")
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pbip-root", type=Path, default=DEFAULT_PBIP_ROOT)
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--phase4a-dir", type=Path, default=DEFAULT_PHASE4A)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--version", default="v1")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_validation(
        args.pbip_root,
        args.model_root,
        args.config,
        args.phase4a_dir,
        args.artifact_root,
        args.version,
    )


if __name__ == "__main__":
    main()
