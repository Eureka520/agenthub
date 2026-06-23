"""Tests for evidence module."""
import json
import hashlib
from pathlib import Path

import pytest

from harness.evidence import scan_stage_dir, merge_manifests, compute_sha256


@pytest.fixture
def stage_dir(tmp_path):
    d = tmp_path / "outputs" / "test_run"
    d.mkdir(parents=True)
    (d / "results.tar.gz").write_bytes(b"fake tarball content")
    (d / "metrics.json").write_text('{"images_processed": 1355}')
    return d


def test_scan_stage_dir(stage_dir):
    entries = scan_stage_dir(str(stage_dir), "test_run")
    assert len(entries) == 2
    for e in entries:
        assert "size" in e
        assert "sha256" in e
        assert e["produced_by_stage"] == "test_run"
        assert e["role"] == "auxiliary"


def test_scan_with_hints(stage_dir):
    hints = [{"path": "results.tar.gz", "label": "推理结果", "role": "required"}]
    (stage_dir / "manifest.hints.json").write_text(json.dumps(hints))
    entries = scan_stage_dir(str(stage_dir), "test_run")
    tar_entry = [e for e in entries if "results.tar.gz" in e["path"]][0]
    assert tar_entry["role"] == "required"
    assert tar_entry["label"] == "推理结果"


def test_scan_with_spec_required(stage_dir):
    entries = scan_stage_dir(str(stage_dir), "test_run", spec_required_paths=["results.tar.gz"])
    tar_entry = [e for e in entries if "results.tar.gz" in e["path"]][0]
    assert tar_entry["role"] == "required"


def test_compute_sha256(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello")
    expected = hashlib.sha256(b"hello").hexdigest()
    assert compute_sha256(str(f)) == expected


def test_merge_manifests(tmp_path):
    m1 = [{"path": "a.txt", "sha256": "aaa", "size": 10, "role": "auxiliary"}]
    m2 = [{"path": "b.txt", "sha256": "bbb", "size": 20, "role": "required"}]
    d1 = tmp_path / "s1"
    d2 = tmp_path / "s2"
    d1.mkdir(); d2.mkdir()
    (d1 / "manifest.json").write_text(json.dumps(m1))
    (d2 / "manifest.json").write_text(json.dumps(m2))
    merged = merge_manifests([
        {"name": "s1", "manifest_path": str(d1 / "manifest.json")},
        {"name": "s2", "manifest_path": str(d2 / "manifest.json")},
    ], task_id="test_task", task_type="inference")
    assert merged["task_id"] == "test_task"
    assert len(merged["stages"]) == 2
    assert merged["summary"]["total_files"] == 2
    assert merged["summary"]["total_size_bytes"] == 30
    assert merged["summary"]["required_count"] == 1
