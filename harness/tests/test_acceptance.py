"""Tests for acceptance check logic."""
import pytest

from harness.acceptance import check_stage_acceptance


@pytest.fixture
def spec():
    return {
        "acceptance_mode": "strict",
        "stages": [
            {
                "name": "test_run",
                "exit_criteria": "推理流程结束",
                "artifacts": [
                    {"path": "outputs/test_run/results.tar.gz", "required": True},
                ],
                "metrics": [
                    {"name": "images_processed", "expect": ">= 1355"},
                ],
            }
        ],
    }


@pytest.fixture
def manifest_pass(tmp_path):
    return [{"path": str(tmp_path / "outputs/test_run/results.tar.gz"), "size": 1000, "sha256": "abc"}]


def test_pass_all(spec, manifest_pass):
    metrics = {"images_processed": 1400}
    result = check_stage_acceptance("test_run", spec, manifest_pass, metrics)
    assert result["result"] == "pass"
    assert result["failures"] == []


def test_fail_missing_artifact(spec):
    result = check_stage_acceptance("test_run", spec, [], {})
    assert result["result"] == "fail"
    assert any(f["kind"] == "artifact_missing" for f in result["failures"])


def test_fail_metric_threshold(spec, manifest_pass):
    metrics = {"images_processed": 1200}
    result = check_stage_acceptance("test_run", spec, manifest_pass, metrics)
    assert result["result"] == "fail"
    assert any(f["kind"] == "metric" for f in result["failures"])


def test_advisory_mode_returns_advisory_fail(spec):
    spec["acceptance_mode"] = "advisory"
    result = check_stage_acceptance("test_run", spec, [], {})
    assert result["result"] == "advisory_fail"


def test_no_matching_stage_passes():
    spec = {"acceptance_mode": "strict", "stages": [{"name": "install"}]}
    result = check_stage_acceptance("nonexistent", spec, [], {})
    assert result["result"] == "pass"
