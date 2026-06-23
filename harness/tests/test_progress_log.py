"""Tests for progress_log module."""
import json
from pathlib import Path

import pytest

from harness.progress_log import ProgressLogger, StageStarted, StageFinished, AcceptanceChecked


@pytest.fixture
def logger(tmp_path):
    log_path = tmp_path / "progress_log.jsonl"
    return ProgressLogger(str(log_path))


def test_emit_stage_started(logger):
    logger.emit(StageStarted(stage="install", depends_on=["container_create"]))
    lines = Path(logger.path).read_text().strip().split("\n")
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["event_type"] == "stage_started"
    assert event["stage"] == "install"
    assert event["payload"]["depends_on"] == ["container_create"]
    assert "ts" in event
    assert "run_id" in event


def test_emit_stage_finished(logger):
    logger.emit(StageFinished(stage="install", status="ok", duration_sec=12.3))
    lines = Path(logger.path).read_text().strip().split("\n")
    event = json.loads(lines[0])
    assert event["event_type"] == "stage_finished"
    assert event["payload"]["status"] == "ok"
    assert event["payload"]["duration_sec"] == 12.3


def test_emit_acceptance_checked(logger):
    logger.emit(AcceptanceChecked(stage="test_run", result="fail", failures=[{"kind": "metric", "detail": "images_processed=1200 < 1355"}]))
    event = json.loads(Path(logger.path).read_text().strip())
    assert event["event_type"] == "acceptance_checked"
    assert event["payload"]["result"] == "fail"


def test_multiple_events_append(logger):
    logger.emit(StageStarted(stage="install", depends_on=[]))
    logger.emit(StageFinished(stage="install", status="ok", duration_sec=5.0))
    lines = Path(logger.path).read_text().strip().split("\n")
    assert len(lines) == 2
