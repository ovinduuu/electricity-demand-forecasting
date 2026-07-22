"""Pure SQL-building helpers used by pipelines/components.py.

Deliberately kept in a module with no `kfp.dsl` decorators: components.py's
extract_training_data component imports from here at runtime (inside the
KFP executor, which re-imports whatever module a component's body pulls
in) - importing anything that re-triggers `@dsl.component(...)` decoration
crashes with `AttributeError: module 'kfp.dsl' has no attribute
'component'`, since the executor's runtime `kfp.dsl` doesn't expose the
authoring-time decorator API (same gotcha the old retail project's
queries.py hit).
"""


def build_extract_query(dataset: str, table: str, start_date: str, end_date: str) -> str:
    """SQL to pull one date range of the fct_demand mart for training."""
    from electricity_demand.models.features import RAW_SOURCE_COLUMNS

    columns = ", ".join(RAW_SOURCE_COLUMNS)
    return (
        f"SELECT {columns} "
        f"FROM `{dataset}.{table}` "
        f"WHERE date BETWEEN '{start_date}' AND '{end_date}' "
        "ORDER BY ba_code, date"
    )
