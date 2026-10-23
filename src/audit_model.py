"""Audit the frozen Phase 3A model without fitting or changing it."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import tempfile
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    log_loss,
    roc_auc_score,
)

from train_models import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    IDENTIFIER_COLUMN,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
    load_analytical_dataset,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "processed" / "telco_churn.duckdb"
DEFAULT_PHASE3A = PROJECT_ROOT / "artifacts" / "phase3a" / "v1"
DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "phase3b"

RANDOM_STATE = 42
PERMUTATION_REPEATS = 20
SMALL_GROUP_N = 100
SMALL_CLASS_N = 20


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_frozen_inputs(
    database_path: Path, phase3a_dir: Path
) -> tuple[Any, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, str]]:
    recorded_hashes = json.loads(
        (phase3a_dir / "artifact_hashes_v1.json").read_text(encoding="utf-8")
    )
    current_hashes: dict[str, str] = {}
    for name, expected_hash in recorded_hashes.items():
        path = phase3a_dir / name
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise ValueError(f"Frozen Phase 3A artifact hash mismatch: {name}")
        current_hashes[name] = actual_hash

    model = joblib.load(phase3a_dir / "churn_model_v1.joblib")
    membership = pd.read_csv(phase3a_dir / "split_membership_v1.csv")
    predictions = pd.read_csv(phase3a_dir / "test_predictions_v1.csv")
    metrics = json.loads((phase3a_dir / "test_metrics_v1.json").read_text(encoding="utf-8"))
    data = load_analytical_dataset(database_path)

    test_ids = set(membership.loc[membership["split"] == "test", IDENTIFIER_COLUMN])
    if test_ids != set(predictions[IDENTIFIER_COLUMN]):
        raise ValueError("Saved predictions do not match the frozen test membership")
    audited = data.merge(predictions, on=IDENTIFIER_COLUMN, how="inner", validate="one_to_one")
    audited = audited.sort_values(IDENTIFIER_COLUMN, kind="mergesort").reset_index(drop=True)
    if len(audited) != metrics["test_customers"]:
        raise ValueError("Frozen prediction row count does not reconcile")
    if not np.array_equal(audited[TARGET_COLUMN].to_numpy(), audited["actual_churn"].to_numpy()):
        raise ValueError("Frozen prediction labels do not match the analytical table")

    recalculated = model.predict_proba(audited[FEATURE_COLUMNS])[:, 1]
    if not np.allclose(
        recalculated,
        audited["predicted_probability"].to_numpy(),
        rtol=0.0,
        atol=1e-14,
    ):
        raise ValueError("Frozen model probabilities do not match the saved test predictions")
    return model, data, membership, audited, metrics, current_hashes


def original_feature_permutation_importance(
    model: Any, audited: pd.DataFrame
) -> pd.DataFrame:
    scores = permutation_importance(
        model,
        audited[FEATURE_COLUMNS],
        audited[TARGET_COLUMN].astype(int),
        scoring={"roc_auc": "roc_auc", "pr_auc": "average_precision"},
        n_repeats=PERMUTATION_REPEATS,
        random_state=RANDOM_STATE,
        n_jobs=1,
    )
    result = pd.DataFrame(
        {
            "feature": FEATURE_COLUMNS,
            "roc_auc_decrease_mean": scores["roc_auc"].importances_mean,
            "roc_auc_decrease_std": scores["roc_auc"].importances_std,
            "pr_auc_decrease_mean": scores["pr_auc"].importances_mean,
            "pr_auc_decrease_std": scores["pr_auc"].importances_std,
            "repeats": PERMUTATION_REPEATS,
        }
    )
    return result.sort_values(
        ["roc_auc_decrease_mean", "feature"], ascending=[False, True], kind="mergesort"
    ).reset_index(drop=True)


def logistic_coefficient_table(model: Any) -> tuple[pd.DataFrame, dict[str, Any]]:
    preprocessor = model.named_steps["preprocess"]
    estimator = model.named_steps["model"]
    coefficients = estimator.coef_.reshape(-1)

    numeric_pipeline = preprocessor.named_transformers_["numeric"]
    numeric_names = list(numeric_pipeline.get_feature_names_out(NUMERIC_FEATURES))
    metadata: list[dict[str, str]] = []
    for name in numeric_names:
        if name.startswith("missingindicator_"):
            original = name.removeprefix("missingindicator_")
            metadata.append(
                {
                    "encoded_feature": name,
                    "original_feature": original,
                    "value_or_scale": "missing indicator (1=missing)",
                    "coefficient_type": "missing_indicator",
                }
            )
        else:
            metadata.append(
                {
                    "encoded_feature": name,
                    "original_feature": name,
                    "value_or_scale": "one training-standard-deviation increase",
                    "coefficient_type": "standardized_numeric",
                }
            )

    categorical_pipeline = preprocessor.named_transformers_["categorical"]
    encoder = categorical_pipeline.named_steps["encoder"]
    encoded_names = list(encoder.get_feature_names_out(CATEGORICAL_FEATURES))
    categorical_metadata: list[tuple[str, str]] = []
    for feature, categories in zip(CATEGORICAL_FEATURES, encoder.categories_, strict=True):
        categorical_metadata.extend((feature, str(category)) for category in categories)
    if len(encoded_names) != len(categorical_metadata):
        raise ValueError("Categorical coefficient metadata does not align with encoder output")
    for encoded_name, (original, category) in zip(
        encoded_names, categorical_metadata, strict=True
    ):
        metadata.append(
            {
                "encoded_feature": encoded_name,
                "original_feature": original,
                "value_or_scale": category,
                "coefficient_type": "one_hot_category",
            }
        )

    if len(metadata) != len(coefficients):
        raise ValueError("Coefficient count does not align with transformed feature count")
    table = pd.DataFrame(metadata)
    table["coefficient"] = coefficients
    table["exp_coefficient"] = np.exp(coefficients)
    table["absolute_coefficient"] = np.abs(coefficients)
    table["absolute_rank"] = table["absolute_coefficient"].rank(
        method="first", ascending=False
    ).astype(int)
    table = table.sort_values("absolute_rank", kind="mergesort").reset_index(drop=True)
    summary = {
        "intercept": float(estimator.intercept_[0]),
        "encoded_coefficient_count": len(coefficients),
        "numeric_output_count": len(numeric_names),
        "categorical_output_count": len(encoded_names),
        "warning": (
            "All one-hot levels are retained. Category coefficients are regularized model "
            "parameters, not reference-category causal effects, and are not uniquely identifiable "
            "as classical unregularized contrasts."
        ),
    }
    return table, summary


def _safe_metric(condition: bool, calculation: Any) -> float | None:
    return float(calculation()) if condition else None


def subgroup_performance(audited: pd.DataFrame) -> pd.DataFrame:
    frame = audited.copy()
    frame["tenure_group"] = pd.cut(
        frame["tenure_months"],
        bins=[-0.001, 0, 12, 24, 48, 60, 72],
        labels=["00 months", "01-12 months", "13-24 months", "25-48 months", "49-60 months", "61-72 months"],
        include_lowest=True,
        right=True,
    ).astype(str)

    rows: list[dict[str, Any]] = []
    for dimension, column in [
        ("gender", "gender"),
        ("contract", "contract"),
        ("tenure_group", "tenure_group"),
    ]:
        for value, group in frame.groupby(column, observed=True, sort=True):
            y_true = group[TARGET_COLUMN].astype(int).to_numpy()
            probability = group["predicted_probability"].to_numpy()
            predicted = group["predicted_churn_at_0_50"].astype(int).to_numpy()
            n = len(group)
            churned = int(y_true.sum())
            retained = n - churned
            tn, fp, fn, tp = confusion_matrix(y_true, predicted, labels=[0, 1]).ravel()
            predicted_positive = int(predicted.sum())
            small = n < SMALL_GROUP_N or churned < SMALL_CLASS_N or retained < SMALL_CLASS_N
            reasons = []
            if n < SMALL_GROUP_N:
                reasons.append(f"n<{SMALL_GROUP_N}")
            if churned < SMALL_CLASS_N:
                reasons.append(f"churned<{SMALL_CLASS_N}")
            if retained < SMALL_CLASS_N:
                reasons.append(f"retained<{SMALL_CLASS_N}")
            rows.append(
                {
                    "dimension": dimension,
                    "group": str(value),
                    "group_size": n,
                    "churned_count": churned,
                    "retained_count": retained,
                    "prevalence": churned / n,
                    "mean_predicted_probability": float(probability.mean()),
                    "calibration_gap": float(probability.mean() - y_true.mean()),
                    "roc_auc": _safe_metric(
                        churned > 0 and retained > 0,
                        lambda: roc_auc_score(y_true, probability),
                    ),
                    "pr_auc": _safe_metric(
                        churned > 0,
                        lambda: average_precision_score(y_true, probability),
                    ),
                    "brier_score": float(brier_score_loss(y_true, probability)),
                    "recall_at_0_50": _safe_metric(churned > 0, lambda: tp / (tp + fn)),
                    "false_positive_rate_at_0_50": _safe_metric(
                        retained > 0, lambda: fp / (fp + tn)
                    ),
                    "precision_at_0_50": _safe_metric(
                        predicted_positive > 0, lambda: tp / predicted_positive
                    ),
                    "small_group_flag": small,
                    "small_group_reason": "; ".join(reasons),
                }
            )
    return pd.DataFrame(rows).sort_values(["dimension", "group"], kind="mergesort")


def risk_deciles(audited: pd.DataFrame, metrics: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    risk = (
        audited.groupby("calibration_decile", sort=True)
        .agg(
            group_size=(IDENTIFIER_COLUMN, "size"),
            churned_count=(TARGET_COLUMN, "sum"),
            mean_predicted_probability=("predicted_probability", "mean"),
            minimum_predicted_probability=("predicted_probability", "min"),
            maximum_predicted_probability=("predicted_probability", "max"),
        )
        .reset_index()
        .sort_values("calibration_decile", kind="mergesort")
    )
    risk["observed_churn_rate"] = risk["churned_count"] / risk["group_size"]
    risk["absolute_calibration_gap"] = (
        risk["mean_predicted_probability"] - risk["observed_churn_rate"]
    ).abs()
    risk["lift_vs_test_prevalence"] = (
        risk["observed_churn_rate"] / metrics["test_prevalence"]
    )
    risk["cumulative_churn_capture"] = risk["churned_count"].cumsum() / metrics["test_churned"]
    ece = float(np.average(risk["absolute_calibration_gap"], weights=risk["group_size"]))
    summary = {
        "test_customers": int(risk["group_size"].sum()),
        "test_churned": int(risk["churned_count"].sum()),
        "test_prevalence": float(metrics["test_prevalence"]),
        "brier_score": float(metrics["brier_score"]),
        "log_loss": float(metrics["log_loss"]),
        "expected_calibration_error_10_equal_count_bins": ece,
        "phase3a_recorded_ece": float(
            metrics["expected_calibration_error_10_equal_count_bins"]
        ),
        "decile_1_is_highest_risk": True,
    }
    if not math.isclose(
        summary["expected_calibration_error_10_equal_count_bins"],
        summary["phase3a_recorded_ece"],
        rel_tol=0.0,
        abs_tol=1e-14,
    ):
        raise ValueError("Calibration ECE does not reconcile with Phase 3A")
    return risk, summary


def run_audit(
    database_path: Path, phase3a_dir: Path, artifact_root: Path, version: str
) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise ValueError("Artifact version may contain only letters, numbers, dot, underscore, and dash")
    target_dir = artifact_root.resolve() / version
    if target_dir.exists():
        raise FileExistsError(f"Audit artifact version already exists: {target_dir}")
    artifact_root.mkdir(parents=True, exist_ok=True)

    model, data, membership, audited, metrics, phase3a_hashes = load_frozen_inputs(
        database_path.resolve(), phase3a_dir.resolve()
    )
    permutation = original_feature_permutation_importance(model, audited)
    coefficients, coefficient_summary = logistic_coefficient_table(model)
    subgroups = subgroup_performance(audited)
    risk, calibration_summary = risk_deciles(audited, metrics)

    test_membership = membership.loc[membership["split"] == "test"]
    manifest = {
        "artifact_version": version,
        "phase3a_artifact_directory": str(phase3a_dir.resolve()),
        "phase3a_source_hashes": phase3a_hashes,
        "phase3a_test_customers": int(metrics["test_customers"]),
        "phase3a_test_churned": int(metrics["test_churned"]),
        "test_membership_customers": len(test_membership),
        "audit_prediction_customers": len(audited),
        "permutation_random_state": RANDOM_STATE,
        "permutation_repeats": PERMUTATION_REPEATS,
        "permutation_unit": "original input feature column",
        "permutation_scoring": ["roc_auc", "average_precision"],
        "small_group_rule": (
            f"Flag when group_size < {SMALL_GROUP_N} or churned_count < {SMALL_CLASS_N} "
            f"or retained_count < {SMALL_CLASS_N}."
        ),
        "shap_used": False,
        "shap_reason": (
            "The selected model is a regularized logistic regression with directly inspectable "
            "coefficients; original-column permutation importance adds held-out global behavior. "
            "SHAP was not needed and would not make correlated-feature effects causal or unique."
        ),
        "model_fit_calls": 0,
    }

    with tempfile.TemporaryDirectory(prefix=f".{version}-", dir=artifact_root.resolve()) as staging:
        staging_dir = Path(staging)
        permutation.to_csv(
            staging_dir / f"permutation_importance_{version}.csv",
            index=False,
            float_format="%.15g",
        )
        coefficients.to_csv(
            staging_dir / f"logistic_coefficients_{version}.csv",
            index=False,
            float_format="%.15g",
        )
        subgroups.to_csv(
            staging_dir / f"subgroup_performance_{version}.csv",
            index=False,
            float_format="%.15g",
        )
        risk.to_csv(
            staging_dir / f"risk_deciles_{version}.csv",
            index=False,
            float_format="%.15g",
        )
        _write_json(staging_dir / f"coefficient_summary_{version}.json", coefficient_summary)
        _write_json(staging_dir / f"calibration_summary_{version}.json", calibration_summary)
        _write_json(staging_dir / f"audit_manifest_{version}.json", manifest)
        hashes = {
            path.name: sha256_file(path)
            for path in sorted(staging_dir.iterdir())
            if path.is_file()
        }
        _write_json(staging_dir / f"artifact_hashes_{version}.json", hashes)
        staging_dir.rename(target_dir)

    print(f"Audit artifacts: {target_dir}")
    print(f"Audited customers: {len(audited)}")
    print(f"Permutation features: {len(permutation)}")
    print(f"Coefficient rows: {len(coefficients)}")
    print(f"Subgroup rows: {len(subgroups)}")
    return target_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--phase3a-dir", type=Path, default=DEFAULT_PHASE3A)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--version", default="v1")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_audit(args.database, args.phase3a_dir, args.artifact_root, args.version)


if __name__ == "__main__":
    main()
