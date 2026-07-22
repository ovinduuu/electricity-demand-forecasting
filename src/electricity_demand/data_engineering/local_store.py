"""Local-file substitute for a BigQuery MERGE, used in local dev (no GCP
project yet - see config.py) - upserts `new_rows` into a local CSV, keyed by
`key_columns`, keeping whichever row has the max `order_column` value per key
so a re-ingested/revised row overwrites the previous one instead of
duplicating it.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def upsert_local_csv(
    path: Path, new_rows: pd.DataFrame, key_columns: list[str], order_column: str
) -> pd.DataFrame:
    path.parent.mkdir(parents=True, exist_ok=True)
    combined = (
        pd.concat([pd.read_csv(path), new_rows], ignore_index=True)
        if path.exists()
        else new_rows.copy()
    )

    # Only the key columns need type-stable comparison for dedup/sort - a
    # round-tripped-through-CSV date string and a fresh datetime.date must
    # compare equal here, or every row would look "new" on every run.
    for col in key_columns:
        combined[col] = combined[col].astype(str)

    combined = combined.sort_values(order_column).drop_duplicates(subset=key_columns, keep="last")
    combined = combined.sort_values(key_columns).reset_index(drop=True)
    combined.to_csv(path, index=False)
    return combined
