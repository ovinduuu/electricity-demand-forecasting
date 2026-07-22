import datetime as dt

from electricity_demand.data_engineering import weather_client


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


def _daily_payload(dates: list[str]) -> _FakeResponse:
    n = len(dates)
    return _FakeResponse(
        {
            "daily": {
                "time": dates,
                "temperature_2m_max": [10.0] * n,
                "temperature_2m_min": [0.0] * n,
                "temperature_2m_mean": [5.0] * n,
            }
        }
    )


def test_fetch_weather_actuals_parses_columnar_response(monkeypatch):
    monkeypatch.setattr(
        weather_client.requests, "get", lambda *a, **k: _daily_payload(["2024-01-01", "2024-01-02"])
    )

    df = weather_client.fetch_weather_actuals(
        39.95, -75.16, "America/New_York", dt.date(2024, 1, 1), dt.date(2024, 1, 2)
    )

    assert list(df.columns) == weather_client.RAW_COLUMNS
    assert df["date"].tolist() == [dt.date(2024, 1, 1), dt.date(2024, 1, 2)]
    assert df["temp_mean_c"].tolist() == [5.0, 5.0]


def test_fetch_weather_actuals_for_all_tags_ba_code(monkeypatch):
    from electricity_demand.data_engineering.balancing_authorities import BalancingAuthority

    monkeypatch.setattr(
        weather_client.requests, "get", lambda *a, **k: _daily_payload(["2024-01-01"])
    )

    bas = [
        BalancingAuthority("PJM", "PJM", "Eastern", "Philadelphia", 0.0, 0.0, "America/New_York"),
        BalancingAuthority(
            "CISO", "CISO", "Pacific", "Sacramento", 0.0, 0.0, "America/Los_Angeles"
        ),
    ]
    df = weather_client.fetch_weather_actuals_for_all(bas, dt.date(2024, 1, 1), dt.date(2024, 1, 1))

    assert len(df) == 2
    assert set(df["ba_code"]) == {"PJM", "CISO"}
