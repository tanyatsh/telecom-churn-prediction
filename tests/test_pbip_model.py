"""Static checks for the Phase 5A PBIP/TMDL semantic model."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from validate_pbip_model import (  # noqa: E402
    DEFAULT_CONFIG,
    DEFAULT_MODEL_ROOT,
    DEFAULT_PBIP_ROOT,
    DEFAULT_PHASE4A,
    EXPECTED_MEASURES,
    EXPECTED_RELATIONSHIPS,
    PARAMETER_TABLES,
    SOURCE_TABLES,
    parse_table_file,
    reconcile_scenario_measures,
    validate_measure_expression_boundaries,
    validate_measures,
    validate_page3_report_design,
    validate_paths,
    validate_project_shell,
    validate_relationship_metadata,
    validate_relationships,
    validate_tables,
)


class PBIPModelChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = PROJECT_ROOT / "artifacts" / "phase5a" / "v1"
        cls.summary = json.loads(
            (cls.artifact / "model_validation_summary_v1.json").read_text(encoding="utf-8")
        )

    def test_project_shell_and_report_pages(self) -> None:
        result = validate_project_shell(DEFAULT_PBIP_ROOT, DEFAULT_MODEL_ROOT)
        self.assertEqual(result["report_pages"], 3)
        self.assertEqual(result["report_visuals"], 39)
        self.assertGreaterEqual(float(result["pbism_version"]), 4.0)

    def test_page3_slicers_dynamic_kpis_and_targeting_contract(self) -> None:
        page3 = (
            DEFAULT_PBIP_ROOT
            / "TelecomChurn.Report"
            / "definition"
            / "pages"
            / "a41c9e7b5d2f4386bc10"
        )
        result = validate_page3_report_design(page3, DEFAULT_MODEL_ROOT)
        self.assertEqual(result["visuals"], 17)
        self.assertEqual(result["slicers"], 6)
        self.assertEqual(result["dynamic_kpis"], 6)
        self.assertEqual(result["targeting_capacity_rows"], 3)
        self.assertEqual(result["layout_bounds"], "PASS")
        self.assertEqual(result["persisted_defaults"], "PASS")

    def test_page3_compact_targeting_and_retrospective_insight(self) -> None:
        visuals = (
            DEFAULT_PBIP_ROOT
            / "TelecomChurn.Report"
            / "definition"
            / "pages"
            / "a41c9e7b5d2f4386bc10"
            / "visuals"
        )
        targeting = json.loads(
            (
                visuals / "20000000000000000015" / "visual.json"
            ).read_text(encoding="utf-8")
        )
        insight = json.loads(
            (
                visuals / "20000000000000000017" / "visual.json"
            ).read_text(encoding="utf-8")
        )

        for key, expected in {"x": 382, "y": 396, "width": 560}.items():
            self.assertAlmostEqual(targeting["position"][key], expected, delta=1)
        self.assertGreaterEqual(targeting["position"]["height"], 190)
        self.assertLessEqual(targeting["position"]["height"], 240)
        projections = targeting["visual"]["query"]["queryState"]["Values"][
            "projections"
        ]
        self.assertEqual(
            [item["field"]["Column"]["Property"] for item in projections],
            [
                "capacity_label",
                "contacted_customers",
                "observed_churn_capture",
                "precision",
                "lift",
            ],
        )
        self.assertEqual(
            [item.get("format", "") for item in projections],
            ["", "#,##0", "0.0%", "0.0%", "0.000"],
        )
        expected_headers = [
            "Capacity",
            "Contacted",
            "Churn captured",
            "Precision",
            "Lift",
        ]
        self.assertEqual(
            [item.get("nativeQueryRef") for item in projections], expected_headers
        )
        self.assertEqual(
            [item.get("displayName") for item in projections], expected_headers
        )
        header_properties = targeting["visual"]["objects"]["columnHeaders"][0][
            "properties"
        ]
        self.assertEqual(
            header_properties["autoSizeColumnWidth"]["expr"]["Literal"]["Value"],
            "false",
        )
        self.assertEqual(
            header_properties["wordWrap"]["expr"]["Literal"]["Value"], "false"
        )
        insight_text = " ".join(
            paragraph["textRuns"][0]["value"]
            for paragraph in insight["visual"]["objects"]["general"][0][
                "properties"
            ]["paragraphs"]
        )
        self.assertIn(
            "Top 20% targeting captures 50% of observed churn, with 2.50x lift.",
            insight_text,
        )
        self.assertIn("RETROSPECTIVE HELD-OUT EVALUATION", insight_text)
        self.assertIn("not a measured retention-campaign outcome", insight_text)
        self.assertLessEqual(
            insight["position"]["y"] + insight["position"]["height"], 720
        )

    def test_final_visual_polish_preserves_bindings_and_layout(self) -> None:
        pages = (
            DEFAULT_PBIP_ROOT
            / "TelecomChurn.Report"
            / "definition"
            / "pages"
        )

        def load(page: str, visual: str) -> dict:
            return json.loads(
                (
                    pages
                    / page
                    / "visuals"
                    / visual
                    / "visual.json"
                ).read_text(encoding="utf-8")
            )

        for visual_id, expected_entity in [
            ("00000000000000000008", "AggChurnByInternetService"),
            ("00000000000000000009", "AggChurnByPaymentMethod"),
        ]:
            visual = load("c29817541de24331942e", visual_id)
            category = visual["visual"]["query"]["queryState"]["Category"][
                "projections"
            ][0]["field"]["Column"]
            self.assertEqual(
                category["Expression"]["SourceRef"]["Entity"], expected_entity
            )
            self.assertEqual(
                visual["visual"]["objects"]["categoryAxis"][0]["properties"][
                    "preferredCategoryWidth"
                ]["expr"]["Literal"]["Value"],
                "8D",
            )
            axis = visual["visual"]["objects"]["categoryAxis"][0]["properties"]
            self.assertEqual(
                axis["innerPadding"]["expr"]["Literal"]["Value"], "12L"
            )
            self.assertEqual(
                axis["outerPadding"]["expr"]["Literal"]["Value"], "0L"
            )

        for visual_id, expected_measure in [
            ("10000000000000000002", "ROC-AUC"),
            ("10000000000000000003", "PR-AUC"),
        ]:
            visual = load("d7f3a6b42c1e4f7890ab", visual_id)
            projection = visual["visual"]["query"]["queryState"]["Data"][
                "projections"
            ][0]
            self.assertEqual(projection["field"]["Measure"]["Property"], expected_measure)
            self.assertEqual(projection["format"], "0.00000")
            self.assertGreaterEqual(visual["position"]["width"], 124)
            self.assertLessEqual(visual["position"]["width"], 145)
            self.assertEqual(
                visual["visual"]["objects"]["value"][0]["properties"]["fontSize"][
                    "expr"
                ]["Literal"]["Value"],
                "17D",
            )

        importance = load(
            "d7f3a6b42c1e4f7890ab", "10000000000000000006"
        )
        self.assertEqual(importance["position"]["width"], 552)
        self.assertEqual(importance["position"]["height"], 372)
        self.assertEqual(
            importance["visual"]["query"]["queryState"]["Y"]["projections"][0][
                "queryRef"
            ],
            "Max(PermutationImportance.roc_auc_decrease_mean)",
        )
        self.assertEqual(
            importance["visual"]["objects"]["categoryAxis"][0]["properties"][
                "preferredCategoryWidth"
            ]["expr"]["Literal"]["Value"],
            "14D",
        )

        calibration = load(
            "d7f3a6b42c1e4f7890ab", "10000000000000000010"
        )
        projections = calibration["visual"]["query"]["queryState"]["Values"][
            "projections"
        ]
        self.assertEqual(
            [projection["nativeQueryRef"] for projection in projections],
            [
                "Risk decile",
                "Customers",
                "Predicted risk",
                "Observed churn",
                "Absolute gap",
            ],
        )
        self.assertEqual(
            [projection["displayName"] for projection in projections],
            [
                "Risk decile",
                "Customers",
                "Predicted risk",
                "Observed churn",
                "Absolute gap",
            ],
        )
        self.assertEqual(
            [projection["format"] for projection in projections],
            ["#,##0", "#,##0", "0.0%", "0.0%", "0.0%"],
        )
        widths = {
            item["selector"]["metadata"]: item["properties"]["value"]["expr"][
                "Literal"
            ]["Value"]
            for item in calibration["visual"]["objects"]["columnWidth"]
        }
        self.assertEqual(
            widths,
            {
                "CalibrationDecile.calibration_decile": "72D",
                "CalibrationDecile.group_size": "68D",
                "CalibrationDecile.mean_predicted_probability": "96D",
                "CalibrationDecile.observed_churn_rate": "96D",
                "CalibrationDecile.absolute_gap": "76D",
            },
        )

        scenario_header = load(
            "a41c9e7b5d2f4386bc10", "20000000000000000002"
        )
        scenario_text = scenario_header["visual"]["objects"]["general"][0][
            "properties"
        ]["paragraphs"][2]["textRuns"][0]["value"]
        self.assertTrue(scenario_text.startswith("Base-case reference:"))
        self.assertEqual(scenario_header["position"]["height"], 80)
        targeting = load("a41c9e7b5d2f4386bc10", "20000000000000000015")
        guide = load("a41c9e7b5d2f4386bc10", "20000000000000000016")
        for key, expected in {"x": 382, "y": 396, "width": 560}.items():
            self.assertAlmostEqual(targeting["position"][key], expected, delta=1)
        self.assertGreaterEqual(targeting["position"]["height"], 190)
        self.assertLessEqual(targeting["position"]["height"], 240)
        table_widths = {
            item["selector"]["metadata"]: item["properties"]["value"]["expr"][
                "Literal"
            ]["Value"]
            for item in targeting["visual"]["objects"]["columnWidth"]
        }
        self.assertEqual(
            table_widths,
            {
                "DimCapacity.capacity_label": "85D",
                "DimCapacity.contacted_customers": "90D",
                "DimCapacity.observed_churn_capture": "140D",
                "DimCapacity.precision": "90D",
                "DimCapacity.lift": "65D",
            },
        )
        insight = load("a41c9e7b5d2f4386bc10", "20000000000000000017")
        insight_text = " ".join(
            paragraph["textRuns"][0]["value"]
            for paragraph in insight["visual"]["objects"]["general"][0][
                "properties"
            ]["paragraphs"]
        )
        self.assertIn(
            "Top 20% targeting captures 50% of observed churn, with 2.50x lift.",
            insight_text,
        )
        self.assertIn("not a measured retention-campaign outcome", insight_text)
        for key, expected in {
            "x": 28,
            "y": 460,
            "width": 330,
            "height": 236,
        }.items():
            self.assertAlmostEqual(guide["position"][key], expected, delta=1)
        for visual in [targeting, insight, guide]:
            self.assertLessEqual(
                visual["position"]["y"] + visual["position"]["height"], 720
            )

    def test_page2_fractional_percentages_scale_exactly_once(self) -> None:
        page = (
            DEFAULT_PBIP_ROOT
            / "TelecomChurn.Report"
            / "definition"
            / "pages"
            / "d7f3a6b42c1e4f7890ab"
            / "visuals"
        )
        risk_visual = json.loads(
            (page / "10000000000000000009" / "visual.json").read_text(
                encoding="utf-8"
            )
        )
        calibration_visual = json.loads(
            (page / "10000000000000000010" / "visual.json").read_text(
                encoding="utf-8"
            )
        )

        risk_query = risk_visual["visual"]["query"]["queryState"]
        self.assertEqual(risk_query["Y"]["projections"][0]["format"], "0.0%")
        risk_tooltip_formats = {
            projection["field"]["Aggregation"]["Expression"]["Column"]["Property"]:
            projection.get("format")
            for projection in risk_query["Tooltips"]["projections"]
        }
        self.assertEqual(
            risk_tooltip_formats["mean_predicted_probability"], "0.0%"
        )
        self.assertEqual(risk_tooltip_formats["cumulative_churn_capture"], "0.0%")
        self.assertEqual(
            risk_visual["visual"]["objects"]["labels"][0]["properties"][
                "valueCustomFormatString"
            ]["expr"]["Literal"]["Value"],
            "'0.0%'",
        )

        calibration_formats = {
            projection["field"]["Column"]["Property"]: projection.get("format")
            for projection in calibration_visual["visual"]["query"]["queryState"][
                "Values"
            ]["projections"]
        }
        for column in [
            "mean_predicted_probability",
            "observed_churn_rate",
            "absolute_gap",
        ]:
            self.assertEqual(calibration_formats[column], "0.0%")
        self.assertNotIn(
            "\\%",
            json.dumps([risk_visual, calibration_visual]),
        )

        risk = pd.read_csv(
            PROJECT_ROOT / "artifacts" / "phase3b" / "v1" / "risk_deciles_v1.csv"
        )
        calibration = pd.read_csv(
            PROJECT_ROOT / "artifacts" / "phase3a" / "v1" / "calibration_v1.csv"
        )
        self.assertEqual(len(risk), 10)
        self.assertEqual(len(calibration), 10)
        for frame, columns in [
            (
                risk,
                [
                    "mean_predicted_probability",
                    "observed_churn_rate",
                    "cumulative_churn_capture",
                ],
            ),
            (
                calibration,
                [
                    "mean_predicted_probability",
                    "observed_churn_rate",
                    "absolute_gap",
                ],
            ),
        ]:
            self.assertTrue(frame[columns].ge(0).all().all())
            self.assertTrue(frame[columns].le(1).all().all())

        self.assertAlmostEqual(
            risk.loc[risk["calibration_decile"] == 1, "observed_churn_rate"].iat[0],
            109 / 141,
            places=12,
        )
        self.assertEqual(
            [f"{value:.1%}" for value in risk["observed_churn_rate"]],
            [
                "77.3%",
                "55.3%",
                "40.4%",
                "34.0%",
                "24.1%",
                "14.2%",
                "13.5%",
                "4.3%",
                "1.4%",
                "0.7%",
            ],
        )
        metrics = json.loads(
            (
                PROJECT_ROOT
                / "artifacts"
                / "phase3a"
                / "v1"
                / "test_metrics_v1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            f"{metrics['expected_calibration_error_10_equal_count_bins']:.2%}",
            "2.44%",
        )

    def test_table_inventory_sources_grains_and_keys(self) -> None:
        parsed, contract = validate_tables(DEFAULT_MODEL_ROOT)
        self.assertEqual(set(parsed), set(SOURCE_TABLES) | PARAMETER_TABLES)
        self.assertEqual(len(contract), len(SOURCE_TABLES))
        self.assertTrue((contract["status"] == "PASS").all())

    def test_relationships_match_and_disconnected_tables_stay_disconnected(self) -> None:
        relationships = validate_relationships(DEFAULT_MODEL_ROOT)
        self.assertEqual(relationships, EXPECTED_RELATIONSHIPS)

    def test_relationship_descriptions_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported description metadata"):
            validate_relationship_metadata(
                "/// Invalid relationship documentation\n"
                "relationship rel_test\n"
                "\tfromColumn: Fact.key\n"
                "\ttoColumn: Dim.key\n"
            )
        with self.assertRaisesRegex(ValueError, "do not support"):
            validate_relationship_metadata(
                "relationship rel_test\n"
                "\tdescription: Invalid metadata\n"
                "\tfromColumn: Fact.key\n"
                "\ttoColumn: Dim.key\n"
            )

    def test_measure_inventory_and_dynamic_leakage_control(self) -> None:
        parsed = {
            path.stem: parse_table_file(path)
            for path in (DEFAULT_MODEL_ROOT / "definition" / "tables").glob("*.tmdl")
        }
        inventory = validate_measures(parsed)
        self.assertEqual(len(inventory), sum(map(len, EXPECTED_MEASURES.values())))

    def test_multiline_measure_expression_boundaries(self) -> None:
        target = (
            DEFAULT_MODEL_ROOT / "definition" / "tables" / "FactTargetCustomer.tmdl"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            validate_measure_expression_boundaries(target, "FactTargetCustomer.tmdl"),
            [
                "Valid Scenario Inputs",
                "Predicted Churn Sum Dynamic",
                "Full-Effect Contribution Dynamic",
            ],
        )
        with self.assertRaisesRegex(ValueError, "one level deeper"):
            validate_measure_expression_boundaries(
                "table T\n"
                "\tmeasure 'Broken Measure' =\n"
                "\t\tVAR Result = 1\n"
                "\t\tRETURN Result\n"
                "\t\tformatString: #,##0\n",
                "broken.tmdl",
            )
        with self.assertRaisesRegex(ValueError, "indented inside the DAX expression"):
            validate_measure_expression_boundaries(
                "table T\n"
                "\tmeasure 'Broken Metadata Boundary' =\n"
                "\t\t\tRETURN 1\n"
                "\t\t\tformatString: #,##0\n",
                "broken-metadata.tmdl",
            )

    def test_portable_parameter_and_no_personal_paths(self) -> None:
        result = validate_paths(DEFAULT_PBIP_ROOT)
        self.assertEqual(result["personal_absolute_path_violations"], 0)
        self.assertEqual(result["forbidden_publishable_files"], [])
        self.assertEqual(result["unapplied_query_changes"], 0)
        self.assertGreater(result["text_files_scanned"], 0)
        self.assertEqual(result["data_root_placeholder"], "<SET_PROJECT_ROOT>")

    def test_all_nine_dynamic_scenario_combinations_reconcile(self) -> None:
        results = reconcile_scenario_measures(DEFAULT_CONFIG, DEFAULT_PHASE4A)
        self.assertEqual(len(results), 9)
        self.assertTrue((results["status"] == "PASS").all())
        default = results.loc[results["is_default_base_20pct"]]
        self.assertEqual(len(default), 1)
        self.assertEqual(int(default.iloc[0]["contacted_customers"]), 282)
        self.assertAlmostEqual(
            float(default.iloc[0]["calculated_net_expected_value"]),
            7022.167726,
            places=6,
        )

    def test_population_scopes_are_explicit_and_distinct(self) -> None:
        self.assertEqual(self.summary["descriptive_population_customers"], 7043)
        self.assertEqual(self.summary["held_out_test_customers"], 1409)
        self.assertNotEqual(
            self.summary["descriptive_population_customers"],
            self.summary["held_out_test_customers"],
        )


if __name__ == "__main__":
    unittest.main()
