# IBM Telco Customer Churn — Data Audit

Audit date: 2026-10-20  
Scope: Phase 1 data acquisition and static quality audit only

## Source and integrity

- Source repository: [IBM/telco-customer-churn-on-icp4d](https://github.com/IBM/telco-customer-churn-on-icp4d)
- Source file page: [Telco-Customer-Churn.csv](https://github.com/IBM/telco-customer-churn-on-icp4d/blob/master/data/Telco-Customer-Churn.csv)
- Direct download URL: [raw CSV](https://raw.githubusercontent.com/IBM/telco-customer-churn-on-icp4d/master/data/Telco-Customer-Churn.csv)
- Local path: `data/raw/Telco-Customer-Churn.csv`
- File size: 970,457 bytes
- SHA-256: `16320c9c1ec72448db59aa0a26a0b95401046bef5d02fd3aeb906448e3055e91`
- Source status: the IBM GitHub repository is public, read-only, and was archived on 2024-07-22.

The raw file is intentionally excluded from Git. Re-download it from the direct URL and verify the hash above to reproduce this audit.

## Shape and schema

- 7,043 data rows (7,044 physical lines including the header)
- 21 columns
- CSV has no embedded type metadata; all values initially arrive as text. Recommended analytical types are inferred from full-column parse checks and observed values.

| Column(s) | Recommended type | Audit note |
|---|---|---|
| `customerID` | string / identifier | 7,043 unique values; all match `NNNN-AAAAA`; exclude from model features. |
| `gender` | categorical | 2 observed values. |
| `SeniorCitizen` | binary integer | 2 observed values (`0`, `1`). |
| `Partner`, `Dependents`, `PhoneService`, `PaperlessBilling` | binary categorical | 2 observed values each. |
| `tenure` | integer | All 7,043 values parse as non-negative integers; 73 distinct values. |
| `MultipleLines`, `InternetService`, `OnlineSecurity`, `OnlineBackup`, `DeviceProtection`, `TechSupport`, `StreamingTV`, `StreamingMovies`, `Contract` | categorical | 3 observed values each. “No phone service” and “No internet service” are structural categories, not missing values. |
| `PaymentMethod` | categorical | 4 observed values. |
| `MonthlyCharges` | decimal | All 7,043 values parse as numeric. |
| `TotalCharges` | nullable decimal | 7,032 numeric values and 11 blanks. |
| `Churn` | binary categorical target | Values are `Yes` and `No`. |

Column order: `customerID`, `gender`, `SeniorCitizen`, `Partner`, `Dependents`, `tenure`, `PhoneService`, `MultipleLines`, `InternetService`, `OnlineSecurity`, `OnlineBackup`, `DeviceProtection`, `TechSupport`, `StreamingTV`, `StreamingMovies`, `Contract`, `PaperlessBilling`, `PaymentMethod`, `MonthlyCharges`, `TotalCharges`, `Churn`.

## Quality findings

| Check | Verified result |
|---|---|
| Missing or blank values | 11 blanks in `TotalCharges`; 0 in every other column |
| Duplicate `customerID` values | 0 duplicate groups; 7,043 unique IDs |
| Exact duplicate rows | 0 |
| `Churn = No` | 5,174 rows (73.463%) |
| `Churn = Yes` | 1,869 rows (26.537%) |

All 11 rows with blank `TotalCharges` have `tenure = 0`. Their `MonthlyCharges` values are populated (range 19.70–80.85), so the blanks are not generic missing records and should be handled with an explicit rule. The target is moderately imbalanced: the majority-to-minority ratio is about 2.77:1.

## Target-leakage review

No explicit leakage field was found: `Churn` is the only outcome column, and no feature is a direct duplicate or obvious encoding of it. Required safeguards for later phases:

- Never include `Churn` or `customerID` in the feature matrix.
- Confirm that every retained feature would be known at the intended scoring time. The source does not document timestamps, prediction horizon, or label-observation windows, so temporal leakage cannot be ruled out from this CSV alone.
- Treat `tenure`, `MonthlyCharges`, and `TotalCharges` as snapshot features, not post-churn information, unless future business metadata says otherwise.
- Fit imputers, encoders, and any resampling only on training folds in a later modeling phase.

## Limitations and decisions needed

- The IBM repository presents the file as a Telco churn dataset, but it does not document collection dates, population/geography, sampling method, customer eligibility, churn definition, or prediction horizon. Representativeness, drift, causal interpretation, and real-world fairness therefore cannot be established.
- There is no event timestamp, so a genuinely time-based validation split is impossible with this file.
- The 11 tenure-zero `TotalCharges` blanks need a documented preprocessing decision. A value of zero is plausible, but that interpretation should be confirmed before modeling; otherwise retain them as missing and estimate handling within training folds.
- Class imbalance should inform later evaluation metrics and decision thresholds, but no resampling decision is needed in Phase 1.
