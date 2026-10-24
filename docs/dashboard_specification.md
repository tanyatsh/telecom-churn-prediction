# Power BI dashboard specification

## Final implementation status

This document began as the design specification for the report. The completed PBIP/PBIR implementation is the authoritative visual inventory; sections explicitly labelled **initial design proposal** are retained to explain the original analytical and layout rationale, not to imply that every proposed visual was built.

| Completed page | Final visual count | Implemented composition |
|---|---:|---|
| Executive Churn Overview | 11 | Header, four descriptive KPI cards, five segment charts, and a key-findings panel |
| Model Performance & Explainability | 11 | Header, four held-out KPI cards, five diagnostic visuals, and an interpretation/limitations panel |
| Retention Strategy & Scenario Simulator | 17 | Header, scenario-reference panel, six slicers, six dynamic KPI cards, retrospective targeting table, decision-boundaries panel, and retrospective insight panel |

The final report therefore contains three 1280×720 pages and 39 native visuals. It preserves the approved population boundaries: Page 1 uses the 7,043-customer descriptive population, while Pages 2 and 3 use the frozen 1,409-customer held-out population where stated.

## Design conventions and analytical contract

The report has three 16:9 pages. Use a compact header with page title, a subtitle identifying the IBM Telco dataset, and a small “retrospective / illustrative” status label. Display percentages to one decimal place in overview charts and two decimals in tooltips. Display value estimates as **currency units**, never with a named currency symbol.

Use only single-select slicers where a calculation requires one capacity or one scenario. Disable irrelevant cross-highlighting between disconnected aggregate visuals. Every tooltip must show the group size or contacted-customer count alongside a rate. Do not expose `customer_id` on a report page.

## Page 1 — Executive Churn Overview

Purpose: describe the audited dataset and observed segment associations without implying causation or time trends.

**Final implementation:** Page 1 contains 11 visuals. The implemented KPI cards show customers, observed churn rate, churned customers, and retained customers. The proposed blank-`TotalCharges` card was not used; the 11 retained null values remain documented as a data-quality finding rather than an executive KPI. All five proposed segment topics were implemented, and the proposed scope text became a verified key-findings and interpretation panel.

### Initial design proposal

Top KPI row proposed during design:

- Customers: `7,043`.
- Churned customers: `1,869`.
- Observed churn rate: `26.537%`.
- Blank `TotalCharges`: `11` retained as null.

Main visual row proposed during design:

1. Horizontal bar chart: churn rate by contract, with `group_size` in the tooltip.
2. Ordered column chart: churn rate by tenure band, with `group_size` and `churned_customers` in the tooltip.
3. Horizontal bar chart: churn rate by internet service.

Lower visual row proposed during design:

1. Bar chart: churn rate by payment method.
2. Ordered column chart: churn rate by monthly-charge band.
3. Text panel: dataset scope and interpretation warning—segment differences are descriptive associations, not intervention effects.

Use the Phase 2 aggregate tables in the data contract. Set all rate fields to **Do not summarize** or use `MAX` at their native grain; never sum rates. Sort tenure and monthly-charge bands with explicit sort columns created in Power Query, not alphabetically.

## Page 2 — Model Performance & Explainability

Purpose: summarize the frozen Logistic Regression model’s held-out discrimination, calibration, operational ranking, and model explanations.

**Final implementation:** Page 2 contains 11 visuals. Four KPI cards show held-out ROC-AUC, PR-AUC, Recall@Top20%, and Lift@Top20%. The retained `PR-AUC` dashboard label and measure represent scikit-learn Average Precision (AP), not trapezoidal precision-recall curve area. Held-out population and prevalence are stated in the header and interpretation panel rather than separate cards, and Brier score is retained in the analytical outputs rather than promoted as a page KPI. The diagnostic area uses a permutation-importance bar chart, a training-only model-comparison bar chart, a confusion-matrix table, an observed-churn risk-decile chart, and a calibration table, plus an interpretation/limitations panel.

The implemented model-comparison and permutation visuals carry uncertainty fields in tooltips rather than drawn error bars. Calibration is shown as a decile table with predicted risk, observed churn, absolute gap, and ECE—not as an identity-line plot. The confusion matrix is a table rather than a heatmap. The risk-decile chart plots observed churn rate and exposes predicted risk and cumulative capture in tooltips. The proposed subgroup reliability matrix was not placed on the final page; subgroup results remain in the validated analytical outputs and documentation.

### Initial design proposal

Top KPI row proposed during design:

- Held-out customers: `1,409`.
- Churn prevalence / AP baseline: `26.5436%`.
- ROC-AUC: `0.843849`.
- Average Precision (AP; retained as `PR-AUC` in the implemented semantic model): `0.659654`.
- Brier score: `0.136785`.
- Recall at top 20%: `50.00%`; lift at top 20%: `2.4982`.

Main visual row proposed during design:

1. Model comparison dot plot: mean five-fold CV ROC-AUC with error bars from `std_cv_roc_auc`; clearly label this as training-only cross-validation.
2. Calibration plot: `mean_predicted_probability` versus `observed_churn_rate` by decile, with a dashed identity reference line. Add expected calibration error `0.024417` in the subtitle.
3. Confusion-matrix heatmap at the declared illustrative threshold `0.50`: TN `920`, FP `115`, FN `175`, TP `199`.

Lower visual row proposed during design:

1. Original-feature permutation-importance bars, sorted by `roc_auc_decrease_mean`, with uncertainty from `roc_auc_decrease_std`.
2. Risk-decile chart with churn rate, mean predicted probability, and cumulative churn capture.
3. Subgroup reliability matrix for gender, contract, and tenure groups. Show `group_size`, `churned_count`, prevalence, ROC-AUC where defined, Brier score, and `small_group_flag`.

Explanatory text must say that permutation importance and Logistic Regression coefficients describe model associations, not causal effects. Undefined subgroup metrics remain blank; do not replace them with zero. Small groups must retain their flag and must not support standalone fairness conclusions.

## Page 3 — Retention Strategy & Scenario Simulator

Purpose: separate retrospective ranking performance from a hypothetical, probability-weighted value simulation.

### Initial fixed-capacity validation proposal

The original design proposed a `DimCapacity` slicer and four fixed-capacity cards. The final page instead presents all three capacities together in a compact retrospective table and adds a clearly labelled held-out insight panel. There is no separate fixed-capacity slicer or card set in the final PBIR page; the live capacity control belongs to the disconnected `pCapacity` scenario inputs.

Use a single-select `DimCapacity[capacity_label]` slicer. Cards show contacted customers, observed churn capture, precision, and lift from `DimCapacity`. A compact table displays all three fixed capacities:

| Capacity | Customers | Observed churn captured | Precision | Lift |
|---:|---:|---:|---:|---:|
| 10% | 141 | 29.1444% | 77.3050% | 2.9124 |
| 20% | 282 | 50.0000% | 66.3121% | 2.4982 |
| 30% | 423 | 65.2406% | 57.6832% | 2.1731 |

Label this section **retrospective held-out evaluation**. Actual churn labels support these aggregate metrics only; they do not select customers.

### Disconnected what-if tables

Create these calculated tables. The permitted capacity values match the validated exports. The other ranges are presentation controls, not validated business assumptions.

```dax
pCapacity =
DATATABLE ( "Value", DOUBLE, { { 0.10 }, { 0.20 }, { 0.30 } } )

pBenefitHorizon = GENERATESERIES ( 1, 24, 1 )
pMargin = GENERATESERIES ( 0.05, 1.00, 0.05 )
pEffectiveness = GENERATESERIES ( 0.00, 1.00, 0.01 )
pContactCost = GENERATESERIES ( 0, 50, 1 )
pOfferCost = GENERATESERIES ( 0, 100, 1 )
```

Leave all six tables disconnected. Recommended defaults reproduce the base scenario at 20% capacity: capacity `0.20`, horizon `6` months, margin `0.55`, effectiveness `0.20`, contact cost `5`, and offer cost `5`.

Effectiveness is a **relative reduction in predicted churn risk among contacted customers**. Contact cost and offer cost are each incurred once for every contacted customer; set offer cost to zero if no offer cost is assumed. Horizon is in months. Monthly charges are in currency units per month. Margin and effectiveness are fractions between zero and one.

### Dynamic measures

Create the following measures. `TOPN` uses the saved deterministic `risk_rank`; `customer_id` is only a tie-breaker and should remain hidden.

```dax
Selected Capacity = SELECTEDVALUE ( pCapacity[Value], 0.20 )
Selected Horizon Months = SELECTEDVALUE ( pBenefitHorizon[Value], 6 )
Selected Margin = SELECTEDVALUE ( pMargin[Value], 0.55 )
Selected Effectiveness = SELECTEDVALUE ( pEffectiveness[Value], 0.20 )
Selected Contact Cost = SELECTEDVALUE ( pContactCost[Value], 5 )
Selected Offer Cost = SELECTEDVALUE ( pOfferCost[Value], 5 )

Valid Scenario Inputs =
VAR Capacity = [Selected Capacity]
VAR Horizon = [Selected Horizon Months]
VAR Margin = [Selected Margin]
VAR Effectiveness = [Selected Effectiveness]
VAR ContactCost = [Selected Contact Cost]
VAR OfferCost = [Selected Offer Cost]
RETURN
    Capacity IN { 0.10, 0.20, 0.30 }
        && Horizon > 0
        && Margin >= 0 && Margin <= 1
        && Effectiveness >= 0 && Effectiveness <= 1
        && ContactCost >= 0
        && OfferCost >= 0

Test Customer Count = COUNTROWS ( ALL ( FactTargetCustomer ) )

Contacted Customers Dynamic =
CEILING ( [Test Customer Count] * [Selected Capacity], 1 )

Predicted Churn Sum Dynamic =
VAR N = [Contacted Customers Dynamic]
VAR Contacted =
    TOPN (
        N,
        ALL ( FactTargetCustomer ),
        FactTargetCustomer[risk_rank], ASC,
        FactTargetCustomer[customer_id], ASC
    )
RETURN
    IF (
        [Valid Scenario Inputs],
        SUMX ( Contacted, FactTargetCustomer[predicted_probability] )
    )

Expected Prevented Churn Dynamic =
[Selected Effectiveness] * [Predicted Churn Sum Dynamic]

Full-Effect Contribution Dynamic =
VAR N = [Contacted Customers Dynamic]
VAR Contacted =
    TOPN (
        N,
        ALL ( FactTargetCustomer ),
        FactTargetCustomer[risk_rank], ASC,
        FactTargetCustomer[customer_id], ASC
    )
RETURN
    IF (
        [Valid Scenario Inputs],
        SUMX (
            Contacted,
            FactTargetCustomer[predicted_probability]
                * FactTargetCustomer[monthly_charges]
                * [Selected Horizon Months]
                * [Selected Margin]
        )
    )

Gross Expected Retained Contribution Dynamic =
[Selected Effectiveness] * [Full-Effect Contribution Dynamic]

Campaign Cost Dynamic =
[Contacted Customers Dynamic]
    * ( [Selected Contact Cost] + [Selected Offer Cost] )

Net Expected Scenario Value Dynamic =
[Gross Expected Retained Contribution Dynamic] - [Campaign Cost Dynamic]

Break-Even Effectiveness Dynamic =
DIVIDE ( [Campaign Cost Dynamic], [Full-Effect Contribution Dynamic] )

Net Expected Value Per Contact Dynamic =
DIVIDE ( [Net Expected Scenario Value Dynamic], [Contacted Customers Dynamic] )
```

Formula definitions, with units:

- Contacted count (customers) = `CEILING(test customers × capacity, 1)`.
- Expected prevented churn (expected customers) = `Σ predicted churn probability × relative risk reduction` over contacted customers.
- Full-effect contribution (currency units) = `Σ probability × monthly charges × horizon months × margin`.
- Gross expected retained contribution (currency units) = `full-effect contribution × effectiveness`.
- Campaign cost (currency units) = `contacted count × (contact cost + offer cost)`.
- Net expected scenario value (currency units) = `gross expected retained contribution − campaign cost`.
- Break-even effectiveness (fraction) = `campaign cost ÷ full-effect contribution`.

The simulator must use the six dynamic measures as its source. The nine rows in `FactScenarioOutcome` are static validation/reference results only; they must not be presented as if they change with what-if controls.

### Final implemented page layout

The final Page 3 composition contains a header, a base-case reference panel, six disconnected single-select slicers, and six dynamic KPI cards for net expected scenario value, gross expected retained contribution, campaign cost, contacted customers, expected prevented churn, and break-even effectiveness. The lower section contains the three-row retrospective targeting table, a decision-boundaries panel, and a retrospective held-out insight panel.

The dynamic measures and defaults above are implemented. `Predicted Churn Sum Dynamic` and `Net Expected Value Per Contact Dynamic` remain available semantic-model measures but are not displayed as separate cards. The proposed waterfall, sensitivity small multiples, and validation bookmark were not included in the final 39-visual report.

### Initial page-layout proposal

Left panel: six input controls with units and a prominent “illustrative assumptions” label. Center KPI row: contacted customers, predicted churn sum, expected prevented churn, gross expected retained contribution, campaign cost, and net expected scenario value. Right KPI cards: break-even effectiveness and net value per contact.

Lower-left: retrospective fixed-capacity table. Lower-center: waterfall from gross expected retained contribution through contact and offer cost to net expected scenario value. Lower-right: one-at-a-time sensitivity small multiples from `FactSensitivity`, explicitly labelled as the base scenario and kept separate from the live simulator.

Add a validation bookmark that selects the base inputs at 10%, 20%, and 30%; the dynamic measures should match the corresponding static base scenario rows within display rounding. This is a report QA aid, not a model-selection step.

## KPI aggregation rules

These rules remain the analytical contract for the implemented report and for any later addition of a visual retained in the initial proposal.

- The final retrospective table displays `DimCapacity` at its native one-row-per-capacity grain. Any future scalar card based on this table must use `SELECTEDVALUE` or `MAX` after enforcing a single capacity; never `SUM` rates or counts across capacities.
- `FactScenarioOutcome` and `FactBreakEven` are static validation/reference tables. Any future scalar card based on them requires exactly one scenario and one capacity.
- `FactSensitivity` small multiples were proposed but not implemented. If added later, each visual must group by exactly one `varied_parameter`; never total across varied values.
- Customer-level dynamic measures always start from `ALL(FactTargetCustomer)` and use exactly one `TOPN` set.
- Page 1 and Page 2 aggregate tables remain disconnected; their materialized rates use `MAX` at the native group grain.

## Limitations and release gates

This dashboard is descriptive and retrospective. It does not demonstrate that contacting a customer prevents churn, estimate treatment uplift, report actual ROI, or establish verified customer lifetime value. Scenario value is an expected value under hypothetical assumptions. Calibration and subgroup results come from one fixed held-out sample. The dataset has no event dates for trend conclusions and no named currency.

For any future PBIX/template export or deployment, confirm:

1. `DataRoot` resolves in Desktop and the intended Service refresh environment.
2. All key columns retain the types in the data contract and all required single-select slicers are enforced.
3. The six dynamic measures reproduce the three static base-scenario values within rounding.
4. Customer-level access, export, and workspace permissions are approved.
5. No local run manifest or personal absolute path is included in the report package.
