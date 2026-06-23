"""Integration test — verifies the three-piece system works end-to-end."""
import json
from pathlib import Path

import pytest

from harness.progress_log import ProgressLogger, StageStarted, StageFinished, EvidenceCollected, AcceptanceChecked
from harness.evidence import scan_stage_dir
from harness.acceptance import check_stage_acceptance


def test_full_stage_flow(tmp_path):
    """Simulate: stage produces files -> evidence collected -> acceptance pass -> events logged."""
    stage_dir = tmp_path / "outputs" / "test_run"
    stage_dir.mkdir(parents=True)
    (stage_dir / "results.tar.gz").write_bytes(b"x" * 100)
    (stage_dir / "metrics.json").write_text('{"images_processed": 1400, "failure_rate": 0.0001}')

    spec = {
        "acceptance_mode": "strict",
        "stages": [{
            "name": "test_run",
            "exit_criteria": "推理完成",
            "artifacts": [{"path": "results.tar.gz", "required": True}],
            "metrics": [
                {"name": "images_processed", "expect": ">= 1355"},
                {"name": "failure_rate", "expect": "<= 0.001"},
            ],
        }],
    }

    log_path = str(tmp_path / "progress_log.jsonl")
    logger = ProgressLogger(log_path, run_id="test_run_001")

    # Execute flow
    logger.emit(StageStarted(stage="test_run", depends_on=[]))
    entries = scan_stage_dir(str(stage_dir), "test_run", ["results.tar.gz"])
    manifest_path = str(stage_dir / "manifest.json")
    Path(manifest_path).write_text(json.dumps(entries, indent=2))
    logger.emit(EvidenceCollected(stage="test_run", manifest_path=manifest_path, entry_count=len(entries)))

    metrics = json.loads((stage_dir / "metrics.json").read_text())
    result = check_stage_acceptance("test_run", spec, entries, metrics)
    logger.emit(AcceptanceChecked(stage="test_run", result=result["result"], failures=result["failures"]))
    logger.emit(StageFinished(stage="test_run", status="ok", duration_sec=42.0))

    # Verify
    assert result["result"] == "pass"
    lines = Path(log_path).read_text().strip().split("\n")
    assert len(lines) == 4
    events = [json.loads(l) for l in lines]
    assert events[0]["event_type"] == "stage_started"
    assert events[1]["event_type"] == "evidence_collected"
    assert events[2]["event_type"] == "acceptance_checked"
    assert events[3]["event_type"] == "stage_finished"
    # Evidence
    assert len(entries) == 2
    tar_entry = [e for e in entries if "results.tar.gz" in e["path"]][0]
    assert tar_entry["role"] == "required"
    assert tar_entry["size"] == 100


def test_acceptance_failure_flow(tmp_path):
    """Simulate: metric violation -> acceptance fail."""
    stage_dir = tmp_path / "outputs" / "test_run"
    stage_dir.mkdir(parents=True)
    (stage_dir / "results.tar.gz").write_bytes(b"x" * 100)
    (stage_dir / "metrics.json").write_text('{"images_processed": 1200}')

    spec = {
        "acceptance_mode": "strict",
        "stages": [{
            "name": "test_run",
            "exit_criteria": "推理完成",
            "artifacts": [{"path": "results.tar.gz", "required": True}],
            "metrics": [{"name": "images_processed", "expect": ">= 1355"}],
        }],
    }

    entries = scan_stage_dir(str(stage_dir), "test_run", ["results.tar.gz"])
    metrics = json.loads((stage_dir / "metrics.json").read_text())
    result = check_stage_acceptance("test_run", spec, entries, metrics)

    assert result["result"] == "fail"
    assert len(result["failures"]) == 1
    assert "1200" in result["failures"][0]["detail"]


def test_advisory_mode_does_not_block(tmp_path):
    """Advisory mode: failures recorded but result is advisory_fail, not fail."""
    stage_dir = tmp_path / "outputs" / "test_run"
    stage_dir.mkdir(parents=True)

    spec = {
        "acceptance_mode": "advisory",
        "stages": [{
            "name": "test_run",
            "artifacts": [{"path": "missing.bin", "required": True}],
            "metrics": [],
        }],
    }

    entries = scan_stage_dir(str(stage_dir), "test_run")
    result = check_stage_acceptance("test_run", spec, entries, {})
    assert result["result"] == "advisory_fail"
    assert len(result["failures"]) >= 1
