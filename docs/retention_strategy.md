# Phase 4A — Retention Prioritization & Business Value Scenarios

Analysis date: 2026-10-20  
Source: frozen Phase 3A `v1` held-out predictions  
Scope: retrospective ranking diagnostics and explicitly hypothetical financial scenarios. No model fitting, threshold tuning, causal-uplift estimation, campaign ROI, or verified customer lifetime value is included.

## Frozen inputs and targeting rule

The analysis verified the SHA-256 hashes of every Phase 3A artifact before reading the fixed 1,409-customer test predictions. Customers are ranked only by descending saved churn probability; `customer_id` ascending breaks exact probability ties. Contact counts are:

`contacted customers = ceil(capacity × 1,409)`

Actual churn labels are used only after ranking to calculate aggregate retrospective capture, precision, and lift. They are not present in the customer targeting export and never determine individual selection.

## Risk-based capacity results

Test churn prevalence is 26.544% (374 of 1,409).

| Fixed capacity | Customers contacted | Observed churners contacted | Observed churn capture | Precision | Lift |
|---|---:|---:|---:|---:|---:|
| Top 10% | 141 | 109 | 29.144% | 77.305% | 2.912 |
| Top 20% | 282 | 187 | 50.000% | 66.312% | 2.498 |
| Top 30% | 423 | 244 | 65.241% | 57.683% | 2.173 |

The ranked list concentrates observed churners substantially above prevalence. Increasing capacity captures more churners in total while lowering precision and lift. These values describe historical test labels, not future campaign response.

## Hypothetical financial model

For each contacted customer `i`:

- `p_i`: frozen predicted churn probability, dimensionless.
- `M_i`: monthly charges, unspecified currency units per month.
- `H`: assumed benefit horizon in months.
- `m`: assumed contribution margin rate, a fraction from 0 to 1.
- `e`: assumed campaign effectiveness, defined as a **relative reduction in churn risk** among contacted customers.
- `C_contact`: contact cost per contacted customer, in currency units.
- `C_offer`: optional offer cost per contacted customer, in currency units.

The offer cost is incurred once for **every contacted customer**, whether or not the customer would have churned, accepts the offer, or is retained. This is a deliberately explicit and conservative incidence rule; it is not derived from observed campaign behavior.

Formulas for a contacted set `S`:

```text
Expected prevented churn count
  = Σ(i in S) p_i × e

Expected gross retained contribution
  = Σ(i in S) p_i × e × M_i × H × m

Total campaign cost
  = |S| × (C_contact + C_offer)

Net expected scenario value
  = expected gross retained contribution − total campaign cost

Break-even effectiveness
  = total campaign cost ÷ Σ(i in S) p_i × M_i × H × m
```

`p_i × e` assumes the same relative risk reduction for every contacted customer. That assumption is not estimated by the churn model and is the largest unresolved causal input. All monetary results use unspecified currency units because the source does not identify a currency.

## Illustrative assumptions

| Scenario | Horizon | Margin | Relative risk reduction | Contact cost | Offer cost | Total cost/contact |
|---|---:|---:|---:|---:|---:|---:|
| Conservative | 3 months | 40% | 10% | 8 | 10 | 18 |
| Base | 6 months | 55% | 20% | 5 | 5 | 10 |
| Optimistic | 12 months | 65% | 30% | 3 | 5 | 8 |

These assumptions are illustrative and not empirically validated.

## Scenario outcomes

“Prevented churn” is an expected count under the assumed relative reduction. “Net scenario value” is not an observed return.

| Scenario | Capacity | Expected prevented churn | Gross retained contribution | Campaign cost | Net expected scenario value | Value/contact |
|---|---:|---:|---:|---:|---:|---:|
| Conservative | 10% | 10.15 | 995.25 | 2,538 | -1,542.75 | -10.94 |
| Conservative | 20% | 18.53 | 1,789.49 | 5,076 | -3,286.51 | -11.65 |
| Conservative | 30% | 25.05 | 2,330.86 | 7,614 | -5,283.14 | -12.49 |
| Base | 10% | 20.29 | 5,473.87 | 1,410 | 4,063.87 | 28.82 |
| Base | 20% | 37.06 | 9,842.17 | 2,820 | 7,022.17 | 24.90 |
| Base | 30% | 50.09 | 12,819.73 | 4,230 | 8,589.73 | 20.31 |
| Optimistic | 10% | 30.44 | 19,407.36 | 1,128 | 18,279.36 | 129.64 |
| Optimistic | 20% | 55.59 | 34,894.96 | 2,256 | 32,638.96 | 115.74 |
| Optimistic | 30% | 75.14 | 45,451.79 | 3,384 | 42,067.79 | 99.45 |

Under the base assumptions, total net scenario value rises through 30% capacity, while value per contact falls as lower-ranked customers are added. This is not a recommended capacity: capacity choice also requires verified treatment uplift, budget, channel constraints, eligibility, customer experience rules, and uncertainty bounds.

## Break-even analysis

| Scenario | Capacity | Assumed effectiveness | Break-even effectiveness | Current cost/contact | Break-even total cost/contact |
|---|---:|---:|---:|---:|---:|
| Conservative | 10% | 10% | 25.50% | 18 | 7.06 |
| Conservative | 20% | 10% | 28.37% | 18 | 6.35 |
| Conservative | 30% | 10% | 32.67% | 18 | 5.51 |
| Base | 10% | 20% | 5.15% | 10 | 38.82 |
| Base | 20% | 20% | 5.73% | 10 | 34.90 |
| Base | 30% | 20% | 6.60% | 10 | 30.31 |
| Optimistic | 10% | 30% | 1.74% | 8 | 137.64 |
| Optimistic | 20% | 30% | 1.94% | 8 | 123.74 |
| Optimistic | 30% | 30% | 2.23% | 8 | 107.45 |

The conservative assumptions do not break even at any evaluated capacity: assumed effectiveness is below the calculated break-even rate, and the 10-unit offer cost alone exceeds the break-even total cost per contact. The base and optimistic cases appear positive only because their assumed effectiveness, horizon, margin, and costs are favorable relative to the model-generated probabilities. They are scenarios, not evidence that a campaign would achieve those values.

## Sensitivity findings

The exported one-way sensitivity table varies one base-case parameter at a time across all capacities.

- At 5% relative risk reduction, base-case net scenario values are negative: -41.53 at 10%, -359.46 at 20%, and -1,025.07 at 30% capacity.
- At 10% effectiveness, they become positive: 1,326.94, 2,101.08, and 2,179.87 respectively.
- At 20% capacity, changing the benefit horizon from 3 to 12 months moves net scenario value from 2,101.08 to 16,864.34.
- At 20% capacity, changing contribution margin from 30% to 70% moves it from 2,548.46 to 9,706.40.
- At 20% capacity under other base assumptions, increasing the offer cost from 0 to 20 per contacted customer lowers net scenario value from 8,432.17 to 2,792.17.

Effectiveness, benefit horizon, and contribution margin drive large changes because all multiply expected retained contribution. Contact and offer costs change value linearly with the number contacted. One-way sensitivity does not represent joint uncertainty or a probability distribution over outcomes.

## Power BI-ready outputs

The Git-ignored `outputs/powerbi/phase4a/v1/` directory contains:

- `capacity_performance_v1.csv`: retrospective capture, precision, and lift by capacity.
- `scenario_assumptions_v1.csv`: labeled assumptions and units.
- `scenario_outcomes_v1.csv`: nine capacity/scenario outcomes.
- `break_even_v1.csv`: break-even effectiveness and cost limits.
- `sensitivity_analysis_v1.csv`: 66 one-way sensitivity rows.
- `customer_targeting_v1.csv`: customer ID, frozen probability, risk rank, monthly charges, capacity flags, and base-case expected values. It intentionally excludes actual churn labels.
- `run_manifest_v1.json` and `output_hashes_v1.json`: source hashes, formulas, rules, and output integrity.

These exports feed the completed three-page `powerbi/TelecomChurn.pbip` report. Its **Retention Strategy & Scenario Simulator** page combines six disconnected what-if slicers, dynamic scenario KPI cards, the three-row retrospective targeting-capacity table, and an interpretation panel. The dynamic financial outputs remain hypothetical calculations from frozen predicted probabilities and selected assumptions; the dashboard does not demonstrate deployed interventions, measured treatment uplift, realized profit, or actual ROI.

## Operational interpretation and unresolved risks

- A churn prediction ranks who is likely to churn. It does not estimate who will respond to an offer. Campaign effectiveness must be measured with a randomized experiment or a defensible causal-uplift design before operational value can be claimed.
- The scenarios assume homogeneous relative effectiveness. Real effectiveness may vary by offer, channel, customer, risk, and capacity.
- Predicted probabilities have calibration error and are based on one random held-out split without temporal or external validation.
- Monthly charges are revenue-like, not verified contribution or customer lifetime value. Margin and horizon are assumptions rather than observed economics.
- Contact and offer costs exclude operational overhead, adverse customer reactions, cannibalization, fraud, capacity constraints, taxes, discounting, and opportunity cost.
- The test set is a portfolio demonstration sample, not a live eligible customer population. Customer consent, suppression lists, fairness, vulnerable-customer policies, and channel eligibility are absent.
- Retrospective capture uses known labels only to evaluate ranking. Those labels would not exist at real scoring time.
