"""Shared `dbt run` invocation, used by both the training pipeline's
run_dbt_transform component (pipelines/components.py) and the daily ingest
jobs (ingest_eia.py, ingest_weather.py) - one place to write the temp
profiles.yml and shell out to dbt instead of several copies of the same
subprocess logic.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

DEFAULT_PROJECT_DIR = "/app/dbt/electricity_demand"


def run_dbt(
    project_id: str,
    bq_location: str = "US",
    project_dir: str = DEFAULT_PROJECT_DIR,
) -> None:
    """Run the dbt project (staging -> marts) against BigQuery.

    Writes a throwaway profiles.yml pointed at `project_id` rather than
    requiring one to be pre-provisioned in the container.
    """
    profiles_dir = Path("/tmp/dbt_profiles")
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "profiles.yml").write_text(
        textwrap.dedent(
            f"""
            electricity_demand:
              target: prod
              outputs:
                prod:
                  type: bigquery
                  method: oauth
                  project: {project_id}
                  dataset: electricity_demand_staging
                  location: {bq_location}
                  threads: 4
            """
        )
    )

    result = subprocess.run(
        [
            "dbt",
            "run",
            "--project-dir",
            project_dir,
            "--profiles-dir",
            str(profiles_dir),
        ],
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(f"dbt run failed with exit code {result.returncode}")
