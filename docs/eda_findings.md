# SQL & Exploratory Data Analysis Findings

Analysis date: 2026-10-20  
Scope: descriptive SQL analysis of the audited IBM Telco Customer Churn CSV. Results describe associations in this dataset; they do not establish causes or future outcomes.

## Reproducible preparation

The pipeline loads the unchanged CSV into `raw.telco_churn` with source fields represented as text. It then creates `analytics.customers`, one typed row per customer, using trimmed strings, `TRY_CAST` for numeric fields, and explicit mappings for binary fields and the churn target.

- 7,043 source rows became 7,043 analytical rows.
- All 7,043 `customer_id` values are present and unique. The identifier is not used as a segment or analytical feature.
- `tenure_months` and `monthly_charges` parsed for every row.
- The 11 whitespace-only source values in `TotalCharges` became 11 SQL `NULL` values; they were not imputed. All occur where `tenure_months = 0`.
- Churn totals reconcile to 1,869 churned and 5,174 retained customers.
- Each of the 12 segment dimensions independently reconciles to 7,043 customers and 1,869 churned customers.

## Overall and numeric profile

Overall churn is 26.537% (1,869 of 7,043).

| Measure | Non-null | Missing | Min | Q1 | Mean | Median | Q3 | Max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Tenure, months | 7,043 | 0 | 0 | 9 | 32.37 | 29 | 55 | 72 |
| Monthly charges | 7,043 | 0 | 18.25 | 35.50 | 64.76 | 70.35 | 89.85 | 118.75 |
| Total charges | 7,032 | 11 | 18.80 | 401.45 | 2,283.30 | 1,397.47 | 3,794.73 | 8,684.80 |

The total-charge mean is well above the median, so one central-value summary alone would not represent that distribution well.

## Segment results

### Contract

| Contract | Customers | Churned | Churn rate |
|---|---:|---:|---:|
| Month-to-month | 3,875 | 1,655 | 42.710% |
| One year | 1,473 | 166 | 11.270% |
| Two year | 1,695 | 48 | 2.832% |

Contract is the clearest descriptive split in the selected summaries. This may overlap with tenure, pricing, or other customer characteristics and should not be interpreted as the isolated effect of contract type.

### Tenure

| Tenure band | Customers | Churned | Churn rate |
|---|---:|---:|---:|
| 0 months | 11 | 0 | 0.000% |
| 1–12 months | 2,175 | 1,037 | 47.678% |
| 13–24 months | 1,024 | 294 | 28.711% |
| 25–48 months | 1,594 | 325 | 20.389% |
| 49–60 months | 832 | 120 | 14.423% |
| 61–72 months | 1,407 | 93 | 6.610% |

Observed churn rates are progressively lower across these tenure bands. The dataset is a snapshot without event dates, so this is a cross-sectional association—not evidence that waiting longer causes retention. The tenure-zero group has only 11 customers and should not be generalized.

### Payment method

| Payment method | Customers | Churned | Churn rate |
|---|---:|---:|---:|
| Electronic check | 2,365 | 1,071 | 45.285% |
| Mailed check | 1,612 | 308 | 19.107% |
| Bank transfer (automatic) | 1,544 | 258 | 16.710% |
| Credit card (automatic) | 1,522 | 232 | 15.243% |

Electronic-check customers have a substantially higher observed churn rate. Payment method may proxy for contract choice, tenure, customer preferences, or eligibility; the table does not show that changing payment method would change churn.

### Internet service

| Internet service | Customers | Churned | Churn rate |
|---|---:|---:|---:|
| Fiber optic | 3,096 | 1,297 | 41.893% |
| DSL | 2,421 | 459 | 18.959% |
| No internet service | 1,526 | 113 | 7.405% |

Fiber-optic customers form a large segment with higher observed churn. This comparison is intertwined with prices, available services, contracts, and customer mix.

### Monthly charges

| Monthly-charge band | Customers | Churned | Churn rate |
|---|---:|---:|---:|
| Below 30 | 1,653 | 162 | 9.800% |
| 30 to below 60 | 1,254 | 327 | 26.077% |
| 60 to below 90 | 2,392 | 807 | 33.737% |
| 90 or more | 1,744 | 573 | 32.856% |

Higher-charge bands have higher observed churn than the lowest band, but the two highest bands are nearly level rather than strictly increasing. The bins are descriptive and were chosen before inspecting the target summaries.

### Other relevant features

- Customers without tech support: 1,446 of 3,473 churned (41.635%); with tech support: 310 of 2,044 (15.166%).
- Customers without online security: 1,461 of 3,498 churned (41.767%); with online security: 295 of 2,019 (14.611%).
- Paperless billing: 1,400 of 4,171 churned (33.565%); non-paperless billing: 469 of 2,872 (16.330%).
- Senior citizens: 476 of 1,142 churned (41.681%); other customers: 1,393 of 5,901 (23.606%).
- Customers without a partner: 1,200 of 3,641 churned (32.958%); with a partner: 669 of 3,402 (19.665%).
- Customers without dependents: 1,543 of 4,933 churned (31.279%); with dependents: 326 of 2,110 (15.450%).
- Gender rates are similar in this sample: 26.921% for 3,488 female customers and 26.160% for 3,555 male customers.

“No internet service” is a structural category for internet-dependent services, not a missing value. It should not be pooled with “No” without a stated analytical reason.

## Business-relevant observations

For later retention analysis, the largest high-rate groups worth examining jointly—not as isolated causes—are month-to-month customers, electronic-check customers, fiber-optic customers, customers in their first 12 tenure months, and customers without online security or tech support. Their overlaps should be quantified before selecting any intervention audience. Counts and expected value should accompany rates so a small high-rate group is not automatically prioritized over a large moderate-rate group.

Gender shows little descriptive separation here, while several service, contract, payment, and lifecycle categories show much larger differences. This is a prioritization clue for deeper analysis, not permission to infer treatment effects or automate customer decisions.

## Limitations and unresolved issues

- The file has no observation date, churn date, prediction horizon, acquisition channel, geography, intervention history, or customer value/margin. Trend, seasonality, cohort, time-to-churn, and causal-retention conclusions are unsupported.
- Segment comparisons are unadjusted. Many dimensions are correlated, and apparent differences may reflect customer mix or product configuration.
- The source does not define how churn was labeled or how customers were sampled, limiting generalizability.
- The 11 missing total charges remain unresolved and intentionally stay `NULL`. A future modeling pipeline must choose a training-fold-safe handling rule.
- Charge and tenure bands are transparent descriptive bins, not target-selected features. Exact-tenure results are exported for audit, but small monthly groups can produce unstable rates.
- Retention actions require cost, margin, contact-policy, eligibility, and experiment data that are not present. Any proposed action should be tested prospectively rather than justified by these associations alone.
