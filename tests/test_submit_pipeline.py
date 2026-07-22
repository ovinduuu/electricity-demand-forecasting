import argparse

import pytest

pytest.importorskip("kfp")

from electricity_demand.pipelines import components  # noqa: E402
from electricity_demand.pipelines.submit_pipeline import (  # noqa: E402
    PlaceholderImageError,
    build_parameter_values,
    check_pipeline_image_is_real,
    compile_pipeline,
    default_pipeline_service_account,
    resolve_date_range,
)


def test_resolve_date_range_defaults_both():
    start, end = resolve_date_range(None, None, lookback_days=730)
    import datetime as dt

    assert end == dt.datetime.now(dt.timezone.utc).date().isoformat()
    assert dt.date.fromisoformat(end) - dt.date.fromisoformat(start) == dt.timedelta(days=730)


def test_resolve_date_range_uses_explicit_end_for_default_start():
    start, end = resolve_date_range(None, "2024-06-01", lookback_days=365)
    assert end == "2024-06-01"
    assert start == "2023-06-02"


def test_resolve_date_range_respects_explicit_start():
    start, end = resolve_date_range("2020-01-01", "2024-06-01")
    assert start == "2020-01-01"
    assert end == "2024-06-01"


def _make_args(**overrides) -> argparse.Namespace:
    defaults = dict(
        project_id="my-project",
        region="us-central1",
        start_date=None,
        end_date="2024-06-01",
        serving_container_image_uri="us-central1-docker.pkg.dev/my-project/electricity-demand/serving:latest",
        serving_model_gcs_path="gs://my-project-raw/models/lightgbm_model.txt",
        bq_location="US",
        valid_days=28,
        mape_threshold=0.08,
        model_display_name="electricity-demand-lightgbm",
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_build_parameter_values_includes_all_pipeline_params():
    params = build_parameter_values(_make_args())

    assert params["project_id"] == "my-project"
    assert params["region"] == "us-central1"
    assert params["end_date"] == "2024-06-01"
    assert params["start_date"] == "2022-06-02"
    assert params["serving_container_image_uri"].startswith("us-central1-docker.pkg.dev")
    assert params["serving_model_gcs_path"] == "gs://my-project-raw/models/lightgbm_model.txt"
    assert params["valid_days"] == 28
    assert params["mape_threshold"] == 0.08


def test_default_pipeline_service_account_matches_terraform_naming():
    assert (
        default_pipeline_service_account("my-project")
        == "electricity-demand-pipeline@my-project.iam.gserviceaccount.com"
    )
    assert (
        default_pipeline_service_account("my-project", sa_name="custom-sa")
        == "custom-sa@my-project.iam.gserviceaccount.com"
    )


def test_check_pipeline_image_is_real_rejects_placeholder(monkeypatch):
    monkeypatch.setattr(components, "PIPELINE_IMAGE", components.PLACEHOLDER_PIPELINE_IMAGE)
    with pytest.raises(PlaceholderImageError):
        check_pipeline_image_is_real()


def test_check_pipeline_image_is_real_accepts_real_image(monkeypatch):
    monkeypatch.setattr(
        components,
        "PIPELINE_IMAGE",
        "us-central1-docker.pkg.dev/my-project/electricity-demand/pipeline:latest",
    )
    check_pipeline_image_is_real()  # should not raise


def test_compile_pipeline_writes_valid_spec(tmp_path):
    out_path = tmp_path / "pipeline.yaml"
    result = compile_pipeline(str(out_path))

    assert result == str(out_path)
    assert out_path.exists()
