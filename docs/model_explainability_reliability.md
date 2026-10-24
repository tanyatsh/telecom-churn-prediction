# Phase 3B — Model Explainability & Reliability Audit

Audit date: 2026-10-20  
Source model: frozen Phase 3A logistic-regression pipeline, artifact version `v1`  
Scope: explain and audit the existing held-out predictions. No model fitting, reselection, recalibration, or threshold adjustment was performed.

## Preservation and method

Before analysis, the audit verified the recorded SHA-256 hash for every Phase 3A artifact and reproduced all 1,409 saved test probabilities from the stored pipeline to numerical tolerance (`1e-14`). The fixed test set contains 374 churners and has 26.544% churn prevalence. Published Phase 3A metrics and the illustrative 0.50 threshold were reused without change.

Two complementary explanation methods were used:

1. **Original-feature permutation importance:** each of the 18 input columns was shuffled as a unit on the fixed test set for 20 deterministic repeats. Importance is the mean decrease in ROC-AUC or Average Precision (AP). AP uses scikit-learn's non-interpolated `average_precision` definition, not trapezoidal precision-recall curve area. This reflects dependence of held-out predictive performance on a column, including its interactions and redundancy with other fields.
2. **Saved logistic-regression coefficients:** coefficients were extracted from the fitted pipeline after imputation, scaling, and one-hot encoding. Numeric coefficients represent a one-training-standard-deviation increase. Categorical coefficients correspond to encoded levels.

SHAP was not used. For this regularized linear model, coefficients already expose the fitted linear score, while original-column permutation importance provides a clearer global held-out check. SHAP would not resolve correlated-feature attribution, redundant service categories, or causality and would add a dependency without changing the core interpretation.

## Original-feature permutation importance

The strongest held-out dependencies were tenure, internet service, monthly charges, total charges, and contract.

| Rank | Original feature | ROC-AUC decrease | Repeat SD | AP decrease |
|---:|---|---:|---:|---:|
| 1 | `tenure_months` | 0.20804 | 0.01159 | 0.29926 |
| 2 | `internet_service` | 0.06913 | 0.00731 | 0.16543 |
| 3 | `monthly_charges` | 0.05927 | 0.00567 | 0.12257 |
| 4 | `total_charges` | 0.03296 | 0.00411 | 0.06843 |
| 5 | `contract` | 0.03168 | 0.00486 | 0.05285 |
| 6 | `streaming_movies` | 0.01242 | 0.00267 | 0.03745 |
| 7 | `streaming_tv` | 0.01101 | 0.00282 | 0.02641 |
| 8 | `online_security` | 0.00432 | 0.00189 | 0.00940 |

The remaining mean ROC-AUC decreases were below 0.0044 each. `partner` had a small negative mean importance (-0.00024), meaning shuffling it very slightly improved ROC-AUC in these repeats. That is best treated as negligible/noisy conditional contribution, not evidence that the attribute is beneficial or harmful.

Permutation importance is not a causal ranking. Correlated features can substitute for each other, so shuffling one may understate their joint role. Conversely, permutation can create unrealistic combinations of tenure, charges, contracts, and services.

## Logistic-regression coefficient interpretation

The largest absolute coefficients in the stored linear score were:

| Encoded input | Coefficient | Direction in fitted score |
|---|---:|---|
| `tenure_months`, standardized | -1.49777 | lower modeled churn score as tenure increases, conditional on all other inputs |
| `monthly_charges`, standardized | -1.09240 | lower modeled score as monthly charges increase, conditional on correlated charge/service fields |
| Fiber-optic internet | +0.81766 | higher modeled score |
| Two-year contract | -0.79292 | lower modeled score |
| DSL internet | -0.78663 | lower modeled score |
| `total_charges`, standardized | +0.76571 | higher modeled score conditional on tenure and monthly charges |
| Month-to-month contract | +0.55440 | higher modeled score |
| Missing `total_charges` indicator | -0.53045 | lower modeled score for the small missing-total pattern |

The negative monthly-charge coefficient does not say that higher charges reduce churn. Monthly charges, total charges, tenure, internet service, streaming services, and contract are correlated. The coefficient describes the fitted conditional linear score when the other encoded fields are held fixed, while the unadjusted EDA compares customer groups directly. Neither is a treatment effect.

All categorical levels were retained by one-hot encoding, and several “No internet service” indicators encode the same structural state. With regularization and redundant columns, individual category coefficients are not classical reference-category contrasts and are not uniquely meaningful in isolation. The original-feature permutation results are the safer summary of global predictive dependence.

The missing-total coefficient is based on only 11 customers in the entire dataset and should not be generalized.

## Held-out subgroup reliability

Metrics below use the unchanged 0.50 threshold and frozen probabilities. A group is flagged when it has fewer than 100 customers or fewer than 20 churned or retained observations. Subgroup differences are descriptive; no confidence intervals, hypothesis tests, multiple-comparison adjustments, or deployment-context fairness criteria are available.

### Gender

Gender was excluded from model features but is used here for audit grouping. Other model inputs may still act as proxies.

| Group | N | Churned | Prevalence | ROC-AUC | AP | Brier | Recall | FPR | Mean probability | Flag |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Female | 716 | 184 | 25.70% | 0.8451 | 0.6691 | 0.1341 | 56.52% | 12.41% | 26.76% | No |
| Male | 693 | 190 | 27.42% | 0.8446 | 0.6551 | 0.1396 | 50.00% | 9.74% | 25.97% | No |

Ranking metrics are very similar across these two groups in this split. Female recall and false-positive rate are higher at the fixed threshold, while mean probability is about 1.07 points above observed prevalence for female customers and 1.45 points below for male customers. These observations are insufficient for a fairness conclusion: only one split and binary source categories are available, uncertainty is unquantified, and relevant policy/context is absent.

### Contract type

| Group | N | Churned | Prevalence | ROC-AUC | AP | Brier | Recall | FPR | Flag |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Month-to-month | 780 | 329 | 42.18% | 0.7520 | 0.6936 | 0.1986 | 60.49% | 25.50% | No |
| One year | 295 | 36 | 12.20% | 0.7176 | 0.2795 | 0.1000 | 0.00% | 0.00% | No |
| Two year | 334 | 9 | 2.69% | 0.8147 | 0.1536 | 0.0249 | 0.00% | 0.00% | **Yes: only 9 churners** |

At 0.50 the model predicts no churners in the one- or two-year groups. That threshold behavior reflects their much lower predicted probabilities and prevalence; it does not mean risk is absent. The two-year ranking metrics are especially uncertain because there are only nine positive cases.

### Tenure groups

| Tenure | N | Churned | Prevalence | ROC-AUC | AP | Brier | Recall | FPR | Calibration gap | Flag |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 0 months | 1 | 0 | 0.00% | — | — | 0.0000 | — | 0.00% | +0.00 pp | **Yes** |
| 1–12 months | 429 | 205 | 47.79% | 0.7758 | 0.7750 | 0.1951 | 69.76% | 31.25% | -0.86 pp | No |
| 13–24 months | 214 | 60 | 28.04% | 0.8298 | 0.5364 | 0.1492 | 63.33% | 18.18% | +4.87 pp | No |
| 25–48 months | 322 | 64 | 19.88% | 0.7822 | 0.4997 | 0.1338 | 25.00% | 6.59% | -0.37 pp | No |
| 49–60 months | 164 | 28 | 17.07% | 0.7744 | 0.4394 | 0.1231 | 7.14% | 0.00% | -3.63 pp | No |
| 61–72 months | 279 | 17 | 6.09% | 0.8343 | 0.3224 | 0.0496 | 0.00% | 0.00% | -0.72 pp | **Yes: only 17 churners** |

Threshold recall declines across the broad tenure groups because modeled risk and observed prevalence decline. That pattern should not be read as time-based validation: the dataset remains a cross-sectional snapshot with no scoring date or outcome horizon.

## Calibration and risk deciles

The Phase 3A diagnostics reconcile exactly:

- Brier score: 0.13678.
- Log loss: 0.41754.
- Expected calibration error across 10 equal-count bins: 0.02442.

Decile 1 is the highest predicted-risk group.

| Risk decile | N | Churned | Observed rate | Mean probability | Lift vs prevalence | Cumulative churn capture |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 141 | 109 | 77.30% | 71.96% | 2.912 | 29.14% |
| 2 | 141 | 78 | 55.32% | 59.46% | 2.084 | 50.00% |
| 3 | 141 | 57 | 40.43% | 46.20% | 1.523 | 65.24% |
| 4 | 141 | 48 | 34.04% | 33.50% | 1.283 | 78.07% |
| 5 | 141 | 34 | 24.11% | 22.91% | 0.908 | 87.17% |
| 6 | 141 | 20 | 14.18% | 15.43% | 0.534 | 92.51% |
| 7 | 141 | 19 | 13.48% | 8.09% | 0.508 | 97.59% |
| 8 | 141 | 6 | 4.26% | 3.93% | 0.160 | 99.20% |
| 9 | 141 | 2 | 1.42% | 1.59% | 0.053 | 99.73% |
| 10 | 140 | 1 | 0.71% | 0.45% | 0.027 | 100.00% |

Observed churn decreases monotonically across risk deciles in this test set. The first two deciles contain exactly half of observed churners, consistent with the published Recall@Top20%. The largest absolute calibration gaps are 5.78 percentage points in decile 3, 5.39 points in decile 7, and 5.35 points in decile 1. No recalibration or threshold change was made from these test results.

## Saved outputs and limitations

`artifacts/phase3b/v1/` contains original-feature permutation importance, all 45 transformed coefficients, subgroup results, risk-decile diagnostics, calibration and coefficient summaries, a source-hash manifest, and output hashes. No new package was added; the existing pinned Phase 3A environment was sufficient.

Key limitations:

- All explanations describe the frozen model and this dataset, not causal drivers or intervention effects.
- Permutation importance can be distorted by correlation and unrealistic shuffled combinations.
- Coefficients depend on preprocessing, scaling, regularization, redundant one-hot columns, and the chosen feature set.
- Subgroup results come from one modest test split. Small positive counts make some estimates unstable or undefined.
- Gender categories are limited to the values supplied by the source dataset, and fairness cannot be assessed comprehensively from gender, contract, and tenure alone.
- The audit does not address temporal drift, external validity, treatment response, operational capacity, or economic value.
