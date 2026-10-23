# Telecom Customer Churn Prediction & Retention Strategy

This portfolio project covers the audited IBM Telco Customer Churn dataset from
data preparation through a completed three-page Power BI decision-support
dashboard. It includes reproducible DuckDB SQL/EDA, deterministic model
evaluation, explainability and reliability checks, retrospective risk-based
targeting, and an explicitly hypothetical retention-value simulator.

The dashboard separates the full 7,043-customer descriptive population from the
frozen 1,409-customer held-out test population. Predictive associations and
scenario outputs are not presented as causal treatment effects, verified
customer lifetime value, or actual campaign ROI.

## Phase 2 pipeline

The pipeline preserves `data/raw/Telco-Customer-Churn.csv`, loads an all-text copy into DuckDB, and creates a typed customer-level analytical table. Blank or whitespace-only `TotalCharges` values remain SQL `NULL`; no imputation is applied.

### Setup and run (Windows PowerShell)

From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python src\prepare_data.py
.\.venv\Scripts\python src\run_eda.py
.\.venv\Scripts\python -m unittest discover -s tests -v
```

Generated, Git-ignored outputs:

- `data/processed/telco_churn.duckdb`
- `outputs/eda/*.csv`

The preparation command runs integrity and reconciliation checks before committing database changes. The tests independently rebuild the database in a temporary directory.

### Main analytical objects

- `raw.telco_churn`: source columns loaded as text.
- `analytics.customers`: one typed row per customer; `customer_id` is retained only as an identifier.
- `analytics.numeric_summary`: descriptive statistics for tenure and charges.
- `analytics.churn_by_segment`: group sizes, churn counts, and churn rates for selected dimensions.
- `analytics.churn_by_tenure_month`: exact-tenure group sizes and churn rates.

Named reproducible EDA queries are in `sql/02_eda_queries.sql`. Verified interpretation is in `docs/eda_findings.md`; source-quality details are in `docs/data_audit.md`.

## Phase 3A modeling

Phase 3A reads the validated DuckDB analytical table without changing it. It creates a deterministic stratified 80/20 split, compares three model families with five-fold cross-validation on the training partition, selects by mean CV ROC-AUC, and evaluates the held-out test partition once.

```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python src\train_models.py
.\.venv\Scripts\python -m unittest discover -s tests -v
```

Versioned outputs are written to the Git-ignored `artifacts/phase3a/v1/` directory. The command refuses to overwrite an existing artifact version. Use a new `--version` value for a later run.

Modeling details and limitations are documented in `docs/model_evaluation.md` after a verified run.

The selected logistic-regression pipeline achieved held-out ROC-AUC 0.84385 and
PR-AUC 0.65965. At the fixed top-20% targeting capacity it captured 50% of
observed churn, corresponding to 2.498x lift over held-out prevalence. These are
frozen test results, not prospective operational performance.

## Phase 3B explainability and reliability audit

Phase 3B loads the frozen Phase 3A `v1` pipeline, split, and held-out predictions. It does not fit or modify a model. The audit calculates original-column permutation importance, extracts logistic-regression coefficients, reports fixed-test subgroup diagnostics, and reconciles calibration/risk deciles.

```powershell
.\.venv\Scripts\python src\audit_model.py
.\.venv\Scripts\python -m unittest discover -s tests -v
```

Outputs are written to the Git-ignored `artifacts/phase3b/v1/` directory. Findings and interpretation limits are documented in `docs/model_explainability_reliability.md`.

## Phase 4A retention prioritization scenarios

Phase 4A consumes the frozen Phase 3A held-out predictions without fitting or changing the model. It evaluates fixed top-risk contact capacities retrospectively and applies explicitly hypothetical, configurable value assumptions.

```powershell
.\.venv\Scripts\python src\retention_scenarios.py
.\.venv\Scripts\python -m unittest discover -s tests -v
```

Power BI-ready CSV outputs are written to the Git-ignored `outputs/powerbi/phase4a/v1/` directory. Assumptions are stored in `config/retention_scenarios_v1.json`; interpretation and formulas are documented in `docs/retention_strategy.md`.

## Phase 4B Power BI contract validation

Phase 4B independently validates all Phase 4A scenario, break-even, sensitivity, capacity, targeting, key, and data-type contracts without changing the exports.

```powershell
.\.venv\Scripts\python src\validate_powerbi_contract.py
.\.venv\Scripts\python -m unittest discover -s tests -v
```

The validated data contract is in `docs/powerbi_data_contract.md`; the three-page report design and dynamic DAX scenario measures are in `docs/dashboard_specification.md`.

## Phase 5 Power BI dashboard

The portable PBIP/PBIR/TMDL project is under `powerbi/`. Its 1280×720 report
contains exactly three approved pages and 39 native visuals:

1. **Executive Churn Overview** — descriptive KPIs and segment-level churn for
   all 7,043 audited customers.
2. **Model Performance & Explainability** — frozen held-out metrics,
   cross-validation comparison, feature importance, risk deciles, calibration,
   and confusion-matrix diagnostics.
3. **Retention Strategy & Scenario Simulator** — six disconnected what-if
   inputs, dynamic financial-scenario measures, and retrospective targeting
   capacity results.

The semantic model contains 19 imported analytical tables, six disconnected
parameter tables, 49 DAX measures, and five relationships. Dynamic scenario
measures use frozen predicted probabilities and illustrative assumptions; they
do not use actual churn labels to calculate expected value and do not estimate
causal uplift.

```powershell
.\.venv\Scripts\python src\validate_pbip_model.py
.\.venv\Scripts\python -m unittest discover -s tests -v
```

The validator checks the three-page/39-visual report contract, table sources,
grains, keys, relationships, disconnected tables, the 49-measure inventory, the
neutral `DataRoot` parameter, Microsoft schema declarations, unresolved Power
Query changes, personal paths, and publication exclusions. It independently
reconciles all nine Phase 4A scenario-capacity outcomes.

Before opening the project on a workstation, generate the ignored Phase 2–4
outputs, open `powerbi/TelecomChurn.pbip`, and set `DataRoot` locally through
Power BI Desktop. Before source control or distribution, restore it to
`<SET_PROJECT_ROOT>`. Manual refresh and verification steps are in
`docs/powerbi_semantic_model.md`.
