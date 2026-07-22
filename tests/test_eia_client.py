import datetime as dt

import pytest

from electricity_demand.data_engineering import eia_client


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


def _page(rows: list[dict], total: int) -> _FakeResponse:
    return _FakeResponse({"response": {"total": str(total), "data": rows}})


def _row(period: str, respondent: str = "PJM", type_: str = "D", value: str = "100") -> dict:
    return {"period": period, "respondent": respondent, "type": type_, "value": value}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("EIA_API_KEY", "test-key")


def test_fetch_demand_requires_api_key(monkeypatch):
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="EIA_API_KEY"):
        eia_client.fetch_demand("PJM", "Eastern", dt.date(2024, 1, 1), dt.date(2024, 1, 2))


def test_fetch_demand_single_page(monkeypatch):
    rows = [_row("2024-01-01"), _row("2024-01-02")]
    monkeypatch.setattr(eia_client.requests, "get", lambda *a, **k: _page(rows, total=2))

    df = eia_client.fetch_demand("PJM", "Eastern", dt.date(2024, 1, 1), dt.date(2024, 1, 2))

    assert list(df.columns) == eia_client.RAW_COLUMNS
    assert len(df) == 2
    assert df["value"].tolist() == [100, 100]
    assert df["period"].tolist() == [dt.date(2024, 1, 1), dt.date(2024, 1, 2)]


def test_fetch_demand_empty_response(monkeypatch):
    monkeypatch.setattr(eia_client.requests, "get", lambda *a, **k: _page([], total=0))

    df = eia_client.fetch_demand("PJM", "Eastern", dt.date(2024, 1, 1), dt.date(2024, 1, 2))

    assert df.empty
    assert list(df.columns) == eia_client.RAW_COLUMNS


def test_fetch_demand_paginates_past_page_size(monkeypatch):
    monkeypatch.setattr(eia_client, "MAX_PAGE_LENGTH", 2)
    all_rows = [_row(f"2024-01-{d:02d}") for d in range(1, 6)]  # 5 rows, page size 2 -> 3 calls
    calls = []

    def fake_get(*_args, **kwargs):
        offset = kwargs["params"]["offset"]
        calls.append(offset)
        page = all_rows[offset : offset + 2]
        return _page(page, total=len(all_rows))

    monkeypatch.setattr(eia_client.requests, "get", fake_get)

    df = eia_client.fetch_demand("PJM", "Eastern", dt.date(2024, 1, 1), dt.date(2024, 1, 5))

    assert calls == [0, 2, 4]
    assert len(df) == 5


def test_fetch_demand_for_all_concatenates_and_tags_each_ba(monkeypatch):
    from electricity_demand.data_engineering.balancing_authorities import BalancingAuthority

    def fake_get(*_args, **kwargs):
        respondent = kwargs["params"]["facets[respondent][]"]
        return _page([_row("2024-01-01", respondent=respondent)], total=1)

    monkeypatch.setattr(eia_client.requests, "get", fake_get)

    bas = [
        BalancingAuthority("PJM", "PJM", "Eastern", "Philadelphia", 0.0, 0.0, "America/New_York"),
        BalancingAuthority(
            "CISO", "CISO", "Pacific", "Sacramento", 0.0, 0.0, "America/Los_Angeles"
        ),
    ]
    df = eia_client.fetch_demand_for_all(bas, dt.date(2024, 1, 1), dt.date(2024, 1, 1))

    assert len(df) == 2
    assert set(df["respondent"]) == {"PJM", "CISO"}
