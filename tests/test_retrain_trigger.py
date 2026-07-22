import sys

import pandas as pd
import pytest

pytest.importorskip("kfp")  # retrain_trigger imports submit_pipeline, which imports kfp

from electricity_demand.monitoring import retrain_trigger  # noqa: E402
from electricity_demand.monitoring.retrain_trigger import (  # noqa: E402
    should_retrain,
    should_retrain_from_drift,
    should_retrain_from_metrics,
)

_BASE_ARGV = [
    "retrain_trigger",
    "--project-id",
    "my-project",
    "--pipeline-root",
    "gs://bucket/root",
    "--serving-container-image-uri",
    "us-central1-docker.pkg.dev/my-project/electricity-demand/serving:latest",
    "--serving-model-gcs-path",
    "gs://bucket/models/lightgbm_model.txt",
]


def _drift_df(*flags: bool) -> pd.DataFrame:
    return pd.DataFrame({"feature": [f"f{i}" for i in range(len(flags))], "drifted": flags})


def test_should_retrain_from_drift_true_when_enough_features_drifted():
    assert should_retrain_from_drift(_drift_df(True, False, False), min_drifted_features=1)
    assert not should_retrain_from_drift(_drift_df(True, False, False), min_drifted_features=2)


def test_should_retrain_from_drift_false_for_empty_or_missing_column():
    assert not should_retrain_from_drift(pd.DataFrame())
    assert not should_retrain_from_drift(pd.DataFrame({"feature": ["f0"]}))


def test_should_retrain_from_metrics_true_when_over_threshold():
    assert should_retrain_from_metrics(0.15, threshold=0.08)
    assert not should_retrain_from_metrics(0.05, threshold=0.08)


def test_should_retrain_from_metrics_false_when_unknown():
    assert not should_retrain_from_metrics(None, threshold=0.08)


def test_should_retrain_combines_drift_and_metrics_with_or():
    no_drift = _drift_df(False, False)
    some_drift = _drift_df(True, False)

    assert should_retrain(some_drift, latest_mape=0.01, mape_threshold=0.08)  # drift alone
    assert should_retrain(no_drift, latest_mape=0.20, mape_threshold=0.08)  # metrics alone
    assert not should_retrain(no_drift, latest_mape=0.01, mape_threshold=0.08)  # neither
    assert should_retrain(some_drift, latest_mape=0.20, mape_threshold=0.08)  # both


def _patch_no_signal_to_retrain(monkeypatch):
    """No drift, MAPE well under threshold - should_retrain() would say no."""
    monkeypatch.setattr(
        retrain_trigger, "_load_latest_drift_results", lambda *a, **k: pd.DataFrame()
    )
    monkeypatch.setattr(retrain_trigger, "_load_latest_mape", lambda *a, **k: 0.01)


def test_main_force_skips_the_gate_and_always_submits(monkeypatch):
    _patch_no_signal_to_retrain(monkeypatch)
    monkeypatch.setattr(retrain_trigger, "check_pipeline_image_is_real", lambda: None)
    monkeypatch.setattr(retrain_trigger, "compile_pipeline", lambda path: path)

    submitted = {}

    def fake_submit(*args, **kwargs):
        submitted["called"] = True
        return type("Job", (), {"resource_name": "fake"})()

    monkeypatch.setattr(retrain_trigger, "submit_pipeline_job", fake_submit)
    monkeypatch.setattr(sys, "argv", [*_BASE_ARGV, "--force"])

    retrain_trigger.main()

    assert submitted.get("called") is True


def test_main_without_force_respects_the_gate(monkeypatch):
    _patch_no_signal_to_retrain(monkeypatch)

    def fail_submit(*args, **kwargs):
        raise AssertionError("should not submit when nothing warrants a retrain")

    monkeypatch.setattr(retrain_trigger, "submit_pipeline_job", fail_submit)
    monkeypatch.setattr(sys, "argv", _BASE_ARGV)

    retrain_trigger.main()  # returns early, no exception, no submission
