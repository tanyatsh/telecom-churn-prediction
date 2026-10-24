# Phase 3A Model Evaluation

Evaluation date: 2026-10-20  
Artifact version: `v1`  
Scope: churn-risk ranking and probability estimation on the validated IBM Telco analytical dataset. No deployment, treatment recommendation, causal claim, or financial-impact estimate is included.

## Protocol

- The 7,043 customers were sorted by `customer_id` before a deterministic stratified 80/20 split using `random_state=42`.
- Training partition: 5,634 customers, including 1,495 churned (26.535%).
- Held-out test partition: 1,409 customers, including 374 churned (26.544%).
- Split membership is saved by customer ID in the ignored versioned artifacts.
- Model selection used stratified five-fold cross-validation on the training partition only. Mean CV ROC-AUC was the declared selection metric.
- All median imputation, missingness indicators, standardization, most-frequent categorical imputation, and one-hot encoding are fitted inside each pipeline and therefore inside each training fold.
- The 11 missing `total_charges` values remain missing in pipeline input. They are imputed only by the fitted numeric preprocessing step.
- The selected pipeline was then evaluated once on the held-out test partition.

## Features and leakage controls

Excluded from predictors:

- `customer_id`: retained only for split membership and prediction reconciliation.
- `gender`: excluded by project requirement.
- `churned`: prediction target.

Included numeric features:

- `tenure_months`
- `monthly_charges`
- `total_charges`

Included categorical features:

- `senior_citizen`, `partner`, `dependents`
- `phone_service`, `multiple_lines`, `internet_service`
- `online_security`, `online_backup`, `device_protection`, `tech_support`
- `streaming_tv`, `streaming_movies`
- `contract`, `paperless_billing`, `payment_method`

The data source provides no feature timestamps or target observation window. Tenure, charges, service states, contract, and billing fields are assumed to be snapshot values available before scoring, but that assumption cannot be verified. `senior_citizen` is an age-related proxy and `partner`/`dependents` are personal attributes; any future use requires governance, subgroup performance review, and a justified business purpose. Full field-level availability notes are stored in `feature_manifest_v1.json`.

## Cross-validation comparison

The table reports the best searched configuration for each model family. Log loss and Brier score are lower-is-better; ROC-AUC and Average Precision (AP) are higher-is-better. AP is calculated with scikit-learn's `average_precision` scorer: the recall-weighted mean of precision across thresholds, not trapezoidal area under an interpolated precision-recall curve. Machine-readable `pr_auc` field names are retained for backward compatibility.

| Model | Best searched configuration | CV ROC-AUC | CV Average Precision (AP) | CV log loss | CV Brier |
|---|---|---:|---:|---:|---:|
| Logistic regression | `C=10`, no class weighting | 0.84556 ± 0.01037 | 0.65362 ± 0.00783 | 0.41777 | 0.13533 |
| Histogram gradient boosting | learning rate 0.05, 15 leaves, L2=1.0 | 0.84418 ± 0.01048 | 0.65674 ± 0.01819 | 0.41836 | 0.13588 |
| Dummy prior classifier | class prior | 0.50000 ± 0.00000 | 0.26535 ± 0.00009 | 0.57858 | 0.19494 |

Logistic regression was selected because it had the highest mean CV ROC-AUC. Its 0.00138 ROC-AUC advantage over histogram gradient boosting is small relative to fold variation; this result does not establish that it will be superior in other samples. The tree model had slightly higher mean CV AP, but AP was not the declared selection criterion.

## Held-out test results

Baseline prevalence is 26.544%. For reference, a non-informative ranking has ROC-AUC 0.5, and the prevalence reference for AP is 0.26544.

| Metric | Held-out result |
|---|---:|
| ROC-AUC | 0.84385 |
| Average Precision (AP) | 0.65965 |
| Log loss | 0.41754 |
| Brier score | 0.13678 |
| Recall at top 20% | 0.50000 |
| Precision at top 20% | 0.66312 |
| Lift at top 20% | 2.49823 |

The top-20% cutoff contains 282 customers. It contains 187 of the 374 observed churners, so it captures 50.0% of test churners. Lift compares this ranked subset with overall test prevalence; it is not an ROI estimate or evidence that contacting these customers will prevent churn.

### Illustrative threshold confusion matrix

The declared illustrative probability threshold is 0.50. It is not an operational threshold and was not selected using costs or intervention capacity.

|  | Predicted retained | Predicted churned |
|---|---:|---:|
| Actual retained | 920 | 115 |
| Actual churned | 175 | 199 |

At this threshold, churn recall is 53.2%, churn precision is 63.4%, and retained-customer specificity is 88.9%. Different operating constraints would require a separately chosen threshold using training/validation information rather than the held-out test labels.

## Calibration diagnostics

- Brier score: 0.13678.
- Log loss: 0.41754.
- Expected calibration error across 10 equal-count test bins: 0.02442, or about 2.44 percentage points.
- In the highest-risk decile, mean predicted probability was 71.96% and observed churn was 77.30%.
- The largest absolute bin gaps were about 5.8 percentage points in the third risk decile and 5.4 points in the seventh.

These are sample diagnostics, not proof of calibration stability. Calibration should be reassessed on newer and operationally representative data before probabilities are used directly.

## Saved artifacts

`artifacts/phase3a/v1/` contains the fitted pipeline, split membership, complete CV search results, model comparison, held-out predictions, confusion matrix, calibration table, metrics, feature and run manifests, package versions, and SHA-256 hashes. The directory is ignored by Git.

The fitted artifact includes preprocessing and the logistic-regression estimator in one scikit-learn `Pipeline`. Recorded core versions are Python 3.13.2, DuckDB 1.5.6, pandas 3.0.6, scikit-learn 1.9.1, NumPy 2.5.4, and SciPy 1.18.1.

## Limitations and unresolved decisions

- The data has no timestamps, label horizon, sampling documentation, acquisition channel, geography, or intervention history. Random stratification cannot test future-time generalization or drift.
- Model selection uncertainty is material because the two non-baseline candidates are close in CV performance.
- Performance has not been evaluated by customer subgroup. Excluding gender from predictors does not remove other proxy or fairness risks.
- The 0.50 threshold and top-20% capacity are illustrative. Operational threshold selection requires contact capacity, error costs, eligibility rules, and prospective validation.
- Test metrics come from one held-out split. External or temporal validation is still required.
- Predictions are associations from historical labels. They do not estimate whether a retention action will work for an individual customer.
