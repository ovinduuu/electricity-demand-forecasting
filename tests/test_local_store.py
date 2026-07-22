import pandas as pd

from electricity_demand.data_engineering.local_store import upsert_local_csv


def test_upsert_creates_file_when_missing(tmp_path):
    path = tmp_path / "raw.csv"
    rows = pd.DataFrame(
        {"ba_code": ["PJM", "CISO"], "date": ["2024-01-01", "2024-01-01"], "value": [1, 2]}
    )

    result = upsert_local_csv(path, rows, key_columns=["ba_code", "date"], order_column="value")

    assert path.exists()
    assert len(result) == 2


def test_upsert_keeps_latest_row_per_key(tmp_path):
    path = tmp_path / "raw.csv"
    first = pd.DataFrame(
        {"ba_code": ["PJM"], "date": ["2024-01-01"], "value": [100], "ingested_at": [1]}
    )
    upsert_local_csv(path, first, key_columns=["ba_code", "date"], order_column="ingested_at")

    revised = pd.DataFrame(
        {"ba_code": ["PJM"], "date": ["2024-01-01"], "value": [999], "ingested_at": [2]}
    )
    result = upsert_local_csv(
        path, revised, key_columns=["ba_code", "date"], order_column="ingested_at"
    )

    assert len(result) == 1
    assert result.iloc[0]["value"] == 999


def test_upsert_appends_new_keys_without_touching_existing(tmp_path):
    path = tmp_path / "raw.csv"
    day1 = pd.DataFrame(
        {"ba_code": ["PJM"], "date": ["2024-01-01"], "value": [1], "ingested_at": [1]}
    )
    upsert_local_csv(path, day1, key_columns=["ba_code", "date"], order_column="ingested_at")

    day2 = pd.DataFrame(
        {"ba_code": ["PJM"], "date": ["2024-01-02"], "value": [2], "ingested_at": [1]}
    )
    result = upsert_local_csv(
        path, day2, key_columns=["ba_code", "date"], order_column="ingested_at"
    )

    assert len(result) == 2
    assert set(result["value"]) == {1, 2}


def test_upsert_overlapping_window_row_count_matches_unique_keys(tmp_path):
    path = tmp_path / "raw.csv"
    window1 = pd.DataFrame(
        {
            "ba_code": ["PJM"] * 5,
            "date": [f"2024-01-0{d}" for d in range(1, 6)],
            "value": range(5),
            "ingested_at": [1] * 5,
        }
    )
    upsert_local_csv(path, window1, key_columns=["ba_code", "date"], order_column="ingested_at")

    window2 = pd.DataFrame(
        {
            "ba_code": ["PJM"] * 5,
            "date": [f"2024-01-0{d}" for d in range(3, 8)],
            "value": range(5),
            "ingested_at": [2] * 5,
        }
    )
    result = upsert_local_csv(
        path, window2, key_columns=["ba_code", "date"], order_column="ingested_at"
    )

    # 5 unique dates in window1 + 5 in window2, overlapping on 01-03..01-05 -> 7 unique dates total.
    assert len(result) == 7
