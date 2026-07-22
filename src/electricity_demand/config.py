"""Central config, loaded from environment variables (see .env.example).

Local dev: `uv run --env-file .env python -m ...` picks up `.env` without
needing a dotenv dependency.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW_DIR = REPO_ROOT / "data" / "raw"
DATA_EXTERNAL_DIR = REPO_ROOT / "data" / "external"


@dataclass(frozen=True)
class GCPConfig:
    project_id: str
    region: str
    raw_bucket: str
    bq_dataset_raw: str
    bq_dataset_staging: str
    bq_dataset_marts: str

    @classmethod
    def from_env(cls) -> GCPConfig:
        return cls(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            region=os.environ.get("GCP_REGION", "us-central1"),
            raw_bucket=os.environ.get("GCS_RAW_BUCKET", ""),
            bq_dataset_raw=os.environ.get("BQ_DATASET_RAW", "electricity_demand_raw"),
            bq_dataset_staging=os.environ.get("BQ_DATASET_STAGING", "electricity_demand_staging"),
            bq_dataset_marts=os.environ.get("BQ_DATASET_MARTS", "electricity_demand_marts"),
        )
