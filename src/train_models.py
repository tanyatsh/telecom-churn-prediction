"""Train and evaluate deterministic Phase 3A churn models."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import os
import platform
import re
import tempfile
from pathlib import Path
from typing import Any

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

import duckdb
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    log_loss,
    roc_auc_score,
)
from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from source_provenance import (
    EXPECTED_IBM_TELCO_CSV_SHA256,
    IBM_TELCO_DATASET_KEY,
    sha256_file,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "processed" / "telco_churn.duckdb"
DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "phase3a"

RANDOM_STATE = 42
TEST_SIZE = 0.20
CV_FOLDS = 5
DECISION_THRESHOLD = 0.50
TOP_FRACTION = 0.20
EXPECTED_ROWS = 7_043
EXPECTED_CHURNED = 1_869

IDENTIFIER_COLUMN = "customer_id"
TARGET_COLUMN = "churned"
EXCLUDED_COLUMNS = [IDENTIFIER_COLUMN, "gender", TARGET_COLUMN]
NUMERIC_FEATURES = ["tenure_months", "monthly_charges", "total_charges"]
CATEGORICAL_FEATURES = [
    "senior_citizen",
    "partner",
    "dependents",
    "phone_service",
    "multiple_lines",
    "internet_service",
    "online_security",
    "online_backup",
    "device_protection",
    "tech_support",
    "streaming_tv",
    "streaming_movies",
    "contract",
    "paperless_billing",
    "payment_method",
]
FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES

DATASET_SQL = """
SELECT
    customer_id,
    gender,
    CAST(senior_citizen AS INTEGER) AS senior_citizen,
    partner,
    dependents,
    tenure_months,
    phone_service,
    multiple_lines,
    internet_service,
    online_security,
    online_backup,
    device_protection,
    tech_support,
    streaming_tv,
    streaming_movies,
    contract,
    paperless_billing,
    payment_method,
    CAST(monthly_charges AS DOUBLE) AS monthly_charges,
    CAST(total_charges AS DOUBLE) AS total_charges,
    CAST(churned AS INTEGER) AS churned
FROM analytics.customers
ORDER BY customer_id
"""

SCORING = {
    "roc_auc": "roc_auc",
    "pr_auc": "average_precision",
    "neg_log_loss": "neg_log_loss",
    "neg_brier": "neg_brier_score",
}

AVAILABILITY_NOTES = {
    "senior_citizen": "Customer attribute; availability must be governed and monitored as an age-related proxy.",
    "partner": "Customer attribute; assumed known at scoring, but update frequency is undocumented.",
    "dependents": "Customer attribute; assumed known at scoring, but update frequency is undocumented.",
    "tenure_months": "Snapshot field; only valid if calculated strictly as of the scoring timestamp.",
    "phone_service": "Current product state; must be captured before the prediction outcome window.",
    "multiple_lines": "Current product state; structural 'No phone service' is retained as a category.",
    "internet_service": "Current product state; must be available before the outcome window.",
    "online_security": "Current service state; structural 'No internet service' is retained.",
    "online_backup": "Current service state; structural 'No internet service' is retained.",
    "device_protection": "Current service state; structural 'No internet service' is retained.",
    "tech_support": "Current service state; structural 'No internet service' is retained.",
    "streaming_tv": "Current service state; structural 'No internet service' is retained.",
    "streaming_movies": "Current service state; structural 'No internet service' is retained.",
    "contract": "Current contract state; renewal or cancellation timing relative to scoring is undocumented.",
    "paperless_billing": "Current billing preference; assumed known before the outcome window.",
    "payment_method": "Current billing method; assumed known before the outcome window.",
    "monthly_charges": "Snapshot charge; billing adjustments after scoring must not be included.",
    "total_charges": "Cumulative snapshot field with 11 missing values; cutoff timing is undocumented.",
}


def load_analytical_dataset(database_path: Path) -> pd.DataFrame:
    if not database_path.is_file():
        raise FileNotFoundError(
            f"Validated DuckDB database not found: {database_path}. Run src/prepare_data.py first."
        )
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        data = connection.execute(DATASET_SQL).fetchdf()
    finally:
        connection.close()

    expected_columns = set(EXCLUDED_COLUMNS + FEATURE_COLUMNS)
    if set(data.columns) != expected_columns:
        raise ValueError(f"Unexpected analytical columns: {sorted(set(data.columns) ^ expected_columns)}")
    if len(data) != EXPECTED_ROWS or data[IDENTIFIER_COLUMN].nunique() != EXPECTED_ROWS:
        raise ValueError("Analytical row count or customer ID uniqueness check failed")
    if int(data[TARGET_COLUMN].sum()) != EXPECTED_CHURNED:
        raise ValueError("Analytical churn total check failed")
    if int(data["total_charges"].isna().sum()) != 11:
        raise ValueError("Expected 11 unmodified missing TotalCharges values")
    return data


def load_verified_source_sha256(database_path: Path) -> str:
    """Read and validate the source CSV provenance stored in DuckDB."""
    if not database_path.is_file():
        raise FileNotFoundError(f"Validated DuckDB database not found: {database_path}")

    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        rows = connection.execute(
            """
            SELECT source_csv_sha256
            FROM metadata.source_provenance
            WHERE dataset_key = ?
            """,
            [IBM_TELCO_DATASET_KEY],
        ).fetchall()
    except duckdb.Error as error:
        raise ValueError("DuckDB source provenance is missing or unreadable") from error
    finally:
        connection.close()

    if len(rows) != 1:
        raise ValueError(
            "DuckDB source provenance must contain exactly one IBM Telco checksum row"
        )
    source_sha256 = str(rows[0][0]).lower()
    if source_sha256 != EXPECTED_IBM_TELCO_CSV_SHA256:
        raise ValueError(
            "Unexpected DuckDB source provenance SHA-256: "
            f"{source_sha256} != {EXPECTED_IBM_TELCO_CSV_SHA256}"
        )
    return source_sha256


def create_split_membership(data: pd.DataFrame) -> pd.DataFrame:
    ordered = data.sort_values(IDENTIFIER_COLUMN, kind="mergesort").reset_index(drop=True)
    train_ids, test_ids = train_test_split(
        ordered[IDENTIFIER_COLUMN].to_numpy(),
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=ordered[TARGET_COLUMN].to_numpy(),
    )
    train_id_set = set(train_ids.tolist())
    membership = ordered[[IDENTIFIER_COLUMN]].copy()
    membership["split"] = np.where(
        membership[IDENTIFIER_COLUMN].isin(train_id_set), "train", "test"
    )
    return membership.sort_values(IDENTIFIER_COLUMN, kind="mergesort").reset_index(drop=True)


def partition_dataset(
    data: pd.DataFrame, membership: pd.DataFrame
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    labeled = data.merge(membership, on=IDENTIFIER_COLUMN, how="inner", validate="one_to_one")
    train = labeled.loc[labeled["split"] == "train"].sort_values(
        IDENTIFIER_COLUMN, kind="mergesort"
    )
    test = labeled.loc[labeled["split"] == "test"].sort_values(
        IDENTIFIER_COLUMN, kind="mergesort"
    )
    return (
        train[FEATURE_COLUMNS].copy(),
        train[TARGET_COLUMN].astype(int).copy(),
        test[FEATURE_COLUMNS].copy(),
        test[TARGET_COLUMN].astype(int).copy(),
    )


def build_preprocessor() -> ColumnTransformer:
    numeric = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("scaler", StandardScaler()),
        ]
    )
    categorical = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )
    return ColumnTransformer(
        transformers=[
            ("numeric", numeric, NUMERIC_FEATURES),
            ("categorical", categorical, CATEGORICAL_FEATURES),
        ],
        remainder="drop",
        sparse_threshold=0.0,
        verbose_feature_names_out=True,
    )


def model_searches() -> dict[str, tuple[Any, dict[str, list[Any]]]]:
    return {
        "dummy": (
            DummyClassifier(random_state=RANDOM_STATE),
            {"model__strategy": ["prior"]},
        ),
        "logistic_regression": (
            LogisticRegression(max_iter=2_000, solver="lbfgs", random_state=RANDOM_STATE),
            {
                "model__C": [0.1, 1.0, 10.0],
                "model__class_weight": [None, "balanced"],
            },
        ),
        "hist_gradient_boosting": (
            HistGradientBoostingClassifier(
                max_iter=150,
                min_samples_leaf=20,
                early_stopping=False,
                random_state=RANDOM_STATE,
            ),
            {
                "model__learning_rate": [0.05, 0.10],
                "model__max_leaf_nodes": [15, 31],
                "model__l2_regularization": [0.0, 1.0],
            },
        ),
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def run_model_selection(
    x_train: pd.DataFrame, y_train: pd.Series
) -> tuple[str, Pipeline, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    cv = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    candidate_rows: list[dict[str, Any]] = []
    comparison_rows: list[dict[str, Any]] = []
    fitted: dict[str, GridSearchCV] = {}

    for model_name, (estimator, parameter_grid) in model_searches().items():
        pipeline = Pipeline(steps=[("preprocess", build_preprocessor()), ("model", estimator)])
        search = GridSearchCV(
            estimator=pipeline,
            param_grid=parameter_grid,
            scoring=SCORING,
            refit="roc_auc",
            cv=cv,
            n_jobs=1,
            return_train_score=False,
            error_score="raise",
        )
        search.fit(x_train, y_train)
        fitted[model_name] = search

        results = search.cv_results_
        for index, parameters in enumerate(results["params"]):
            candidate_rows.append(
                {
                    "model": model_name,
                    "parameters": json.dumps(parameters, sort_keys=True, default=_json_value),
                    "mean_cv_roc_auc": results["mean_test_roc_auc"][index],
                    "std_cv_roc_auc": results["std_test_roc_auc"][index],
                    "mean_cv_pr_auc": results["mean_test_pr_auc"][index],
                    "std_cv_pr_auc": results["std_test_pr_auc"][index],
                    "mean_cv_log_loss": -results["mean_test_neg_log_loss"][index],
                    "mean_cv_brier": -results["mean_test_neg_brier"][index],
                    "rank_cv_roc_auc": results["rank_test_roc_auc"][index],
                }
            )

        best_index = search.best_index_
        comparison_rows.append(
            {
                "model": model_name,
                "best_parameters": json.dumps(
                    search.best_params_, sort_keys=True, default=_json_value
                ),
                "mean_cv_roc_auc": results["mean_test_roc_auc"][best_index],
                "std_cv_roc_auc": results["std_test_roc_auc"][best_index],
                "mean_cv_pr_auc": results["mean_test_pr_auc"][best_index],
                "std_cv_pr_auc": results["std_test_pr_auc"][best_index],
                "mean_cv_log_loss": -results["mean_test_neg_log_loss"][best_index],
                "mean_cv_brier": -results["mean_test_neg_brier"][best_index],
            }
        )

    comparison = pd.DataFrame(comparison_rows).sort_values(
        ["mean_cv_roc_auc", "model"], ascending=[False, True], kind="mergesort"
    ).reset_index(drop=True)
    selected_name = str(comparison.loc[0, "model"])
    selected_search = fitted[selected_name]
    selection = {
        "selection_metric": "mean_cv_roc_auc",
        "selected_model": selected_name,
        "selected_parameters": {
            key: _json_value(value) for key, value in selected_search.best_params_.items()
        },
        "selected_mean_cv_roc_auc": float(selected_search.best_score_),
    }
    candidates = pd.DataFrame(candidate_rows).sort_values(
        ["model", "rank_cv_roc_auc", "parameters"], kind="mergesort"
    )
    return selected_name, selected_search.best_estimator_, comparison, candidates, selection


def evaluate_test_set(
    model: Pipeline,
    data: pd.DataFrame,
    membership: pd.DataFrame,
    x_test: pd.DataFrame,
    y_test: pd.Series,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    test_customers = (
        data.merge(membership, on=IDENTIFIER_COLUMN, how="inner", validate="one_to_one")
        .loc[lambda frame: frame["split"] == "test", [IDENTIFIER_COLUMN]]
        .sort_values(IDENTIFIER_COLUMN, kind="mergesort")
        .reset_index(drop=True)
    )
    probabilities = model.predict_proba(x_test)[:, 1]
    predictions = test_customers.copy()
    predictions["actual_churn"] = y_test.to_numpy(dtype=int)
    predictions["predicted_probability"] = probabilities
    predictions["predicted_churn_at_0_50"] = (probabilities >= DECISION_THRESHOLD).astype(int)
    predictions = predictions.sort_values(
        ["predicted_probability", IDENTIFIER_COLUMN],
        ascending=[False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    predictions["risk_rank"] = np.arange(1, len(predictions) + 1)
    top_count = math.ceil(TOP_FRACTION * len(predictions))
    predictions["top_20_percent"] = predictions["risk_rank"] <= top_count

    y_true = predictions["actual_churn"].to_numpy(dtype=int)
    y_probability = predictions["predicted_probability"].to_numpy(dtype=float)
    y_predicted = predictions["predicted_churn_at_0_50"].to_numpy(dtype=int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_predicted, labels=[0, 1]).ravel()

    prevalence = float(y_true.mean())
    top = predictions.loc[predictions["top_20_percent"]]
    top_churned = int(top["actual_churn"].sum())
    recall_at_top = top_churned / int(y_true.sum())
    precision_at_top = top_churned / top_count
    lift_at_top = precision_at_top / prevalence

    predictions["calibration_decile"] = np.minimum(
        ((predictions["risk_rank"] - 1) * 10 // len(predictions)) + 1, 10
    )
    calibration = (
        predictions.groupby("calibration_decile", sort=True)
        .agg(
            group_size=(IDENTIFIER_COLUMN, "size"),
            mean_predicted_probability=("predicted_probability", "mean"),
            observed_churn_rate=("actual_churn", "mean"),
        )
        .reset_index()
    )
    calibration["absolute_gap"] = (
        calibration["mean_predicted_probability"] - calibration["observed_churn_rate"]
    ).abs()
    expected_calibration_error = float(
        np.average(calibration["absolute_gap"], weights=calibration["group_size"])
    )

    metrics = {
        "test_customers": len(predictions),
        "test_churned": int(y_true.sum()),
        "test_prevalence": prevalence,
        "baseline_roc_auc": 0.5,
        "baseline_pr_auc": prevalence,
        "roc_auc": float(roc_auc_score(y_true, y_probability)),
        "pr_auc": float(average_precision_score(y_true, y_probability)),
        "log_loss": float(log_loss(y_true, y_probability, labels=[0, 1])),
        "brier_score": float(brier_score_loss(y_true, y_probability)),
        "expected_calibration_error_10_equal_count_bins": expected_calibration_error,
        "illustrative_threshold": DECISION_THRESHOLD,
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "top_fraction": TOP_FRACTION,
        "top_customer_count": top_count,
        "top_churned_count": top_churned,
        "recall_at_top_20_percent": float(recall_at_top),
        "precision_at_top_20_percent": float(precision_at_top),
        "lift_at_top_20_percent": float(lift_at_top),
    }
    confusion = pd.DataFrame(
        [[tn, fp], [fn, tp]],
        index=["actual_retained", "actual_churned"],
        columns=["predicted_retained", "predicted_churned"],
    ).rename_axis("actual_class").reset_index()
    predictions = predictions.sort_values(IDENTIFIER_COLUMN, kind="mergesort").reset_index(drop=True)
    return metrics, predictions, confusion, calibration


def package_versions() -> dict[str, str]:
    packages = ["duckdb", "pandas", "numpy", "scipy", "scikit-learn", "joblib"]
    versions = {name: importlib.metadata.version(name) for name in packages}
    versions["python"] = platform.python_version()
    versions["platform"] = platform.platform()
    return versions


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def train_and_evaluate(database_path: Path, artifact_root: Path, version: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise ValueError("Artifact version may contain only letters, numbers, dot, underscore, and dash")
    target_dir = artifact_root.resolve() / version
    if target_dir.exists():
        raise FileExistsError(f"Artifact version already exists; choose a new --version: {target_dir}")
    artifact_root.mkdir(parents=True, exist_ok=True)

    database_path = database_path.resolve()
    source_sha256 = load_verified_source_sha256(database_path)
    data = load_analytical_dataset(database_path)
    membership = create_split_membership(data)
    x_train, y_train, x_test, y_test = partition_dataset(data, membership)
    selected_name, selected_model, comparison, candidates, selection = run_model_selection(
        x_train, y_train
    )
    metrics, predictions, confusion, calibration = evaluate_test_set(
        selected_model, data, membership, x_test, y_test
    )

    with tempfile.TemporaryDirectory(prefix=f".{version}-", dir=artifact_root.resolve()) as staging:
        staging_dir = Path(staging)
        membership.to_csv(staging_dir / f"split_membership_{version}.csv", index=False)
        comparison.to_csv(staging_dir / f"model_comparison_{version}.csv", index=False, float_format="%.12g")
        candidates.to_csv(staging_dir / f"cv_results_{version}.csv", index=False, float_format="%.12g")
        predictions.to_csv(staging_dir / f"test_predictions_{version}.csv", index=False, float_format="%.15g")
        confusion.to_csv(staging_dir / f"confusion_matrix_{version}.csv", index=False)
        calibration.to_csv(staging_dir / f"calibration_{version}.csv", index=False, float_format="%.12g")
        joblib.dump(selected_model, staging_dir / f"churn_model_{version}.joblib", compress=3)
        _write_json(staging_dir / f"test_metrics_{version}.json", metrics)
        _write_json(staging_dir / f"package_versions_{version}.json", package_versions())
        _write_json(
            staging_dir / f"feature_manifest_{version}.json",
            {
                "identifier": IDENTIFIER_COLUMN,
                "target": TARGET_COLUMN,
                "excluded_columns": EXCLUDED_COLUMNS,
                "included_features": FEATURE_COLUMNS,
                "numeric_features": NUMERIC_FEATURES,
                "categorical_features": CATEGORICAL_FEATURES,
                "scoring_time_availability_notes": AVAILABILITY_NOTES,
            },
        )
        run_manifest = {
            "artifact_version": version,
            "database": str(database_path.resolve()),
            "random_state": RANDOM_STATE,
            "test_size": TEST_SIZE,
            "cv_folds": CV_FOLDS,
            "selection": selection,
            "selected_model": selected_name,
            "train_rows": len(x_train),
            "test_rows": len(x_test),
            "train_churned": int(y_train.sum()),
            "test_churned": int(y_test.sum()),
            "train_prevalence": float(y_train.mean()),
            "test_prevalence": float(y_test.mean()),
            "missing_total_charges_before_preprocessing": int(data["total_charges"].isna().sum()),
            "raw_csv_sha256": source_sha256,
            "test_policy": "Test labels were used once, after CV model selection, for final evaluation only.",
        }
        _write_json(staging_dir / f"run_manifest_{version}.json", run_manifest)

        file_hashes = {
            path.name: sha256_file(path)
            for path in sorted(staging_dir.iterdir())
            if path.is_file()
        }
        _write_json(staging_dir / f"artifact_hashes_{version}.json", file_hashes)
        staging_dir.rename(target_dir)

    print(f"Selected model: {selected_name}")
    print(f"Artifacts: {target_dir}")
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return target_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--version", default="v1")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    train_and_evaluate(args.database, args.artifact_root, args.version)


if __name__ == "__main__":
    main()
