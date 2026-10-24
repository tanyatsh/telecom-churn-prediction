"""Shared source-file provenance constants and helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path


IBM_TELCO_DATASET_KEY = "ibm_telco_customer_churn"
EXPECTED_IBM_TELCO_CSV_SHA256 = (
    "16320c9c1ec72448db59aa0a26a0b95401046bef5d02fd3aeb906448e3055e91"
)


def sha256_file(path: Path) -> str:
    """Return the lowercase SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
