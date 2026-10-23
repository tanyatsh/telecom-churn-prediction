# Power BI data contract

## Scope and validation status

This contract prepares the frozen Phase 2, Phase 3, and Phase 4A analytical outputs for a future three-page Power BI report. It does not change the source SQL, trained model, held-out predictions, or Phase 4A calculations.

The Phase 4B validator independently rebuilt every Phase 4A calculation from the frozen held-out predictions, typed analytical data, and versioned scenario configuration. Validation passed for all 3 capacity rows, 9 scenario outcomes, 9 break-even rows, and 66 one-at-a-time sensitivity rows. All six CSV exports had the expected row counts, unique non-null keys, compatible column types, and no unexpected null cells. Recorded Phase 4A file hashes also matched.

One portability inconsistency was identified before any dashboard work: the ignored Phase 3A, Phase 3B, and Phase 4A run-manifest JSON files contain absolute local paths. They are audit artifacts only and must not be imported into or distributed with the Power BI report. The CSV exports, tracked configuration, scripts, and documentation do not require a personal workstation path.

## Portable source contract

Create one required Power Query text parameter named `DataRoot`. It must point to either the project root or a deployed copy with the same relative folder structure. Every query must construct its source from `DataRoot` plus one of the relative paths below. Do not store a personal drive or user-profile path in a PBIX, template, query, or tracked file.

```powerquery
let
    Root = Text.TrimEnd(DataRoot, {"\\", "/"}),
    RelativePath = "outputs\\powerbi\\phase4a\\v1\\capacity_performance_v1.csv",
    Source = Csv.Document(
        File.Contents(Root & "\\" & RelativePath),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
    ),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true])
in
    Headers
```

For a Power BI Service deployment, stage the approved CSV set in an organizational data location and change only the connection implementation or parameter value; keep the logical table and column contract unchanged. Do not publish customer-level exports to a broadly accessible location.

## Phase 4A tables

Percentages and rates are stored as decimal fractions and must be formatted as percentages in Power BI. Monetary-looking values use **unspecified currency units** and must not be formatted with a named currency symbol.

| Power BI table | Relative file | Grain | Primary key | Rows |
|---|---|---|---|---:|
| `DimCapacity` | `outputs/powerbi/phase4a/v1/capacity_performance_v1.csv` | One row per fixed contact capacity, including its retrospective performance attributes | `capacity_fraction` | 3 |
| `DimScenario` | `outputs/powerbi/phase4a/v1/scenario_assumptions_v1.csv` | One row per illustrative scenario | `name` | 3 |
| `FactScenarioOutcome` | `outputs/powerbi/phase4a/v1/scenario_outcomes_v1.csv` | One row per scenario and fixed capacity | `scenario`, `capacity_fraction` | 9 |
| `FactBreakEven` | `outputs/powerbi/phase4a/v1/break_even_v1.csv` | One row per scenario and fixed capacity | `scenario`, `capacity_fraction` | 9 |
| `FactSensitivity` | `outputs/powerbi/phase4a/v1/sensitivity_analysis_v1.csv` | One row per varied parameter, value, and fixed capacity | `varied_parameter`, `varied_value`, `capacity_fraction` | 66 |
| `FactTargetCustomer` | `outputs/powerbi/phase4a/v1/customer_targeting_v1.csv` | One row per held-out customer | `customer_id` | 1,409 |

### Column types

`DimCapacity`

- Decimal number: `capacity_fraction`, `observed_churn_capture`, `precision`, `test_prevalence`, `lift`.
- Whole number: `test_customers`, `contacted_customers`, `observed_churned_contacted`, `total_test_churned`.
- Text: `capacity_label`, `selection_rule`.

`DimScenario`

- Text: `name`, `currency_unit`, `effectiveness_definition`, `offer_cost_incidence`, `assumption_status`.
- Whole number: `benefit_horizon_months`.
- Decimal number: `contribution_margin_rate`, `relative_risk_reduction`, `contact_cost_per_customer`, `offer_cost_per_customer`.

`FactScenarioOutcome`

- Text: `scenario`, `capacity_label`, `offer_cost_incidence`.
- Whole number: `contacted_customers`, `benefit_horizon_months`.
- Decimal number: `capacity_fraction`, `contribution_margin_rate`, `relative_risk_reduction`, `contact_cost_per_customer`, `offer_cost_per_customer`, `predicted_churn_sum_contacted`, `average_predicted_churn_probability`, `average_monthly_charges`, `expected_prevented_churn`, `probability_weighted_contribution_at_full_effect`, `gross_expected_retained_contribution`, `contact_cost_total`, `offer_cost_total`, `total_campaign_cost`, `net_expected_scenario_value`, `net_expected_value_per_contact`, `break_even_effectiveness`, `break_even_total_cost_per_contact`, `break_even_contact_cost_after_offer`.

`FactBreakEven`

- Text: `scenario`, `capacity_label`, `offer_cost_incidence`.
- Whole number: `contacted_customers`, `benefit_horizon_months`.
- Decimal number: `capacity_fraction`, `contribution_margin_rate`, `relative_risk_reduction`, `contact_cost_per_customer`, `offer_cost_per_customer`, `break_even_effectiveness`, `break_even_total_cost_per_contact`, `break_even_contact_cost_after_offer`, `current_total_cost_per_contact`.

`FactSensitivity`

- Text: `base_scenario`, `varied_parameter`, `capacity_label`.
- Whole number: `contacted_customers`.
- Decimal number: `varied_value`, `capacity_fraction`, `net_expected_scenario_value`, `gross_expected_retained_contribution`, `total_campaign_cost`, `expected_prevented_churn`. `varied_value` remains decimal because it represents parameters with different units.

`FactTargetCustomer`

- Text: `customer_id`.
- Whole number: `risk_rank`.
- Decimal number: `predicted_probability`, `monthly_charges`, `base_expected_prevented_churn`, `base_expected_gross_retained_contribution`, `base_cost_if_contacted`, `base_net_expected_value_if_contacted`.
- True/false: `selected_top_10pct`, `selected_top_20pct`, `selected_top_30pct`.

`customer_id` is an identifier only. Set it to **Do not summarize**, hide it from report authors unless a controlled operational drill-through is approved, and never display it in tracked documentation. `FactTargetCustomer` intentionally omits the actual churn label; actual labels are used only in the aggregate retrospective capacity table.

## Model

Import the capacity-performance CSV directly as `DimCapacity`. Its three capacity rows are unique, and its retrospective metrics are attributes of those fixed capacity choices. Hide duplicate capacity labels on facts after relationships are established.

Use single-direction, one-to-many relationships:

| From | Cardinality | To | Key | Active |
|---|---|---|---|---|
| `DimCapacity` | 1:* | `FactScenarioOutcome` | `capacity_fraction` | Yes |
| `DimCapacity` | 1:* | `FactBreakEven` | `capacity_fraction` | Yes |
| `DimCapacity` | 1:* | `FactSensitivity` | `capacity_fraction` | Yes |
| `DimScenario` | 1:* | `FactScenarioOutcome` | `name` to `scenario` | Yes |
| `DimScenario` | 1:* | `FactBreakEven` | `name` to `scenario` | Yes |

Do not relate fact tables directly. Do not use bidirectional filtering. Keep `FactTargetCustomer` disconnected from `DimCapacity` and scenario tables: dynamic targeting is calculated from `risk_rank`, not from the three nested Boolean flags. Keep `FactSensitivity` disconnected from `DimScenario` because all 66 rows are one-at-a-time perturbations of the base scenario, not three scenario outcomes.

The Power BI what-if tables `pCapacity`, `pBenefitHorizon`, `pMargin`, `pEffectiveness`, `pContactCost`, and `pOfferCost` are disconnected parameter tables. They must not filter any imported table through a model relationship.

## Supporting page-level tables

These existing validated outputs can be loaded as small, disconnected aggregate tables. Their measures are already materialized at their stated grain, so relationships are neither needed nor desirable.

| Table | Relative file | Grain / key |
|---|---|---|
| `KPIOverallChurn` | `outputs/eda/overall_summary.csv` | One dataset summary row |
| `AggChurnByContract` | `outputs/eda/churn_by_contract.csv` | One row per `contract` |
| `AggChurnByTenureBand` | `outputs/eda/churn_by_tenure_band.csv` | One row per `tenure_band` |
| `AggChurnByInternetService` | `outputs/eda/churn_by_internet_service.csv` | One row per `internet_service` |
| `AggChurnByPaymentMethod` | `outputs/eda/churn_by_payment_method.csv` | One row per `payment_method` |
| `AggChurnByMonthlyChargeBand` | `outputs/eda/churn_by_monthly_charge_band.csv` | One row per `monthly_charge_band` |
| `ModelComparison` | `artifacts/phase3a/v1/model_comparison_v1.csv` | One row per `model` |
| `CalibrationDecile` | `artifacts/phase3a/v1/calibration_v1.csv` | One row per `calibration_decile` |
| `ConfusionMatrix` | `artifacts/phase3a/v1/confusion_matrix_v1.csv` | One row per `actual_class` |
| `PermutationImportance` | `artifacts/phase3b/v1/permutation_importance_v1.csv` | One row per original `feature` |
| `SubgroupPerformance` | `artifacts/phase3b/v1/subgroup_performance_v1.csv` | One row per `dimension`, `group` |
| `RiskDecile` | `artifacts/phase3b/v1/risk_deciles_v1.csv` | One row per `calibration_decile` |

The Phase 3 metric JSON is a validated scalar source. Either expose its fields through a one-row Power Query table named `KPIModelTest` or enter the frozen values as measures with the JSON retained as the source of record. Do not import model binaries, hash manifests, split membership, or run manifests into Power BI.

## Reconciled Phase 4A reference values

The following values are static validation references, not estimates that respond to what-if controls.

| Scenario | Capacity | Contacted | Net expected scenario value | Break-even effectiveness |
|---|---:|---:|---:|---:|
| Conservative | 10% | 141 | -1,542.75075 | 25.5011% |
| Conservative | 20% | 282 | -3,286.51496 | 28.3657% |
| Conservative | 30% | 423 | -5,283.13922 | 32.6660% |
| Base | 10% | 141 | 4,063.87087 | 5.1517% |
| Base | 20% | 282 | 7,022.16773 | 5.7304% |
| Base | 30% | 423 | 8,589.73427 | 6.5992% |
| Optimistic | 10% | 141 | 18,279.36036 | 1.7437% |
| Optimistic | 20% | 282 | 32,638.95830 | 1.9395% |
| Optimistic | 30% | 423 | 42,067.78513 | 2.2336% |

## Double-counting controls

- The 10%, 20%, and 30% audiences are nested. Never add capacity rows or sum the three Boolean selection flags.
- Conservative, base, and optimistic rows are mutually exclusive alternatives. Require a single scenario for scenario KPIs; never sum across scenarios.
- Break-even rates, precision, lift, capture, averages, and probabilities are non-additive. Use the selected row, not `SUM`.
- Sensitivity rows change one parameter at a time from the base scenario. Do not aggregate different parameters or values into a business total.
- Dynamic value measures must rank `FactTargetCustomer` once and aggregate the selected customers once. Do not combine those measures with precomputed `base_*` columns or static scenario outcomes.
- Use actual churn only in aggregate retrospective metrics. It must not enter the simulator or individual targeting decision.
- Turn off automatic date/time and implicit measures for this model; neither is useful here.

## Limitations

The held-out data is a retrospective sample, not a live campaign population. Predicted churn risk is not causal treatment uplift. Effectiveness, margin, horizon, contact cost, and offer cost are hypothetical inputs and are not empirically validated. The source supplies no timestamps for trend analysis, no named currency, no measured intervention response, and no verified customer lifetime value. Subgroup metrics describe this fixed test sample and are not, by themselves, fairness conclusions.
