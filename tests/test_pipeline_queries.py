from electricity_demand.pipelines.queries import build_extract_query


def test_build_extract_query_includes_table_and_date_range():
    query = build_extract_query(
        dataset="electricity_demand_marts",
        table="fct_demand",
        start_date="2024-01-01",
        end_date="2024-03-01",
    )

    assert "`electricity_demand_marts.fct_demand`" in query
    assert "'2024-01-01'" in query
    assert "'2024-03-01'" in query
    assert "ORDER BY ba_code, date" in query
