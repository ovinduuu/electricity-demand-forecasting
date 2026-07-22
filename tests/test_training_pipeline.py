import pytest
import yaml

pytest.importorskip("kfp")

from kfp import compiler  # noqa: E402

from electricity_demand.pipelines.training_pipeline import training_pipeline  # noqa: E402


def test_pipeline_compiles_to_valid_spec(tmp_path):
    out_path = tmp_path / "pipeline.yaml"

    compiler.Compiler().compile(training_pipeline, package_path=str(out_path))

    assert out_path.exists()
    spec = yaml.safe_load(out_path.read_text())
    assert spec["pipelineInfo"]["name"] == "electricity-demand-training"


def test_pipeline_graph_wires_expected_dependencies(tmp_path):
    out_path = tmp_path / "pipeline.yaml"
    compiler.Compiler().compile(training_pipeline, package_path=str(out_path))
    spec = yaml.safe_load(out_path.read_text())

    tasks = spec["root"]["dag"]["tasks"]
    assert set(tasks) == {
        "run-dbt-transform",
        "extract-training-data",
        "train-model",
        "condition-1",
    }
    assert tasks["run-dbt-transform"].get("dependentTasks", []) == []
    assert tasks["extract-training-data"]["dependentTasks"] == ["run-dbt-transform"]
    assert tasks["train-model"]["dependentTasks"] == ["extract-training-data"]
    assert tasks["condition-1"]["dependentTasks"] == ["train-model"]


def test_pipeline_requires_serving_container_image_uri_parameter():
    params = training_pipeline.pipeline_spec.root.input_definitions.parameters
    assert "serving_container_image_uri" in params
    assert "serving_model_gcs_path" in params
