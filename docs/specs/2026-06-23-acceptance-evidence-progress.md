# AcceptanceSpec / EvidenceManifest / ProgressLog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Phase 1 three-piece verification system: AcceptanceSpec (contract), EvidenceManifest (facts), ProgressLog (audit trail) in the harness.

**Architecture:** Each piece is a standalone module (`progress_log.py`, `evidence.py`) plus integration hooks in existing orchestrator nodes/graph. The flow is: stage runs → `_collect_evidence` → `_check_acceptance` → emit events → `final_acceptance` node aggregates all.

**Tech Stack:** Python 3.10+, Pydantic (already used in schemas/), PyYAML, existing LangGraph orchestrator.

---

### Task 1: ProgressLog Module

**Files:**
- Create: `harness/progress_log.py`
- Test: `harness/tests/test_progress_log.py`

- [ ] **Step 1: Write failing tests for ProgressLogger**

```python
"""Tests for progress_log module."""
import json
import tempfile
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /nexus/agenthub && python -m pytest harness/tests/test_progress_log.py -v`
Expected: ImportError — `harness.progress_log` does not exist yet.

- [ ] **Step 3: Implement ProgressLogger**

```python
"""ProgressLog — append-only JSONL audit trail for harness decisions."""

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class StageStarted:
    stage: str
    depends_on: list[str] = field(default_factory=list)
    _event_type: str = field(default="stage_started", init=False)


@dataclass
class StageFinished:
    stage: str
    status: str
    duration_sec: float
    _event_type: str = field(default="stage_finished", init=False)


@dataclass
class EvidenceCollected:
    stage: str
    manifest_path: str
    entry_count: int
    _event_type: str = field(default="evidence_collected", init=False)


@dataclass
class AcceptanceChecked:
    stage: str
    result: str  # "pass" | "fail"
    failures: list[dict] = field(default_factory=list)
    _event_type: str = field(default="acceptance_checked", init=False)


@dataclass
class ErrorRaised:
    stage: str
    error_code: str
    level: str
    match_pattern: str = ""
    _event_type: str = field(default="error_raised", init=False)


@dataclass
class RetryTriggered:
    stage: str
    attempt: int
    reason: str
    diagnosis: str = ""
    _event_type: str = field(default="retry_triggered", init=False)


@dataclass
class KnowledgeUpdated:
    stage: str
    target_file: str
    section: str
    _event_type: str = field(default="knowledge_updated", init=False)


@dataclass
class FinalAcceptance:
    stage: str  # "__final__"
    overall: str  # "pass" | "fail"
    summary: dict = field(default_factory=dict)
    _event_type: str = field(default="final_acceptance", init=False)


class ProgressLogger:
    """Append-only JSONL logger for harness events."""

    def __init__(self, path: str, run_id: str = ""):
        self.path = path
        self.run_id = run_id or f"run_{int(time.time())}"
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event) -> None:
        """Serialize and append event to JSONL file."""
        payload = {k: v for k, v in asdict(event).items() if not k.startswith("_")}
        payload.pop("stage", None)
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "run_id": self.run_id,
            "stage": event.stage,
            "event_type": event._event_type,
            "payload": payload,
        }
        with open(self.path, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /nexus/agenthub && python -m pytest harness/tests/test_progress_log.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /nexus/agenthub && git add harness/progress_log.py harness/tests/test_progress_log.py
git commit -m "feat(harness): add ProgressLog JSONL audit trail module"
```

---

### Task 2: Evidence Module

**Files:**
- Create: `harness/evidence.py`
- Test: `harness/tests/test_evidence.py`

- [ ] **Step 1: Write failing tests**

```python
"""Tests for evidence module."""
import json
import hashlib
import tempfile
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
    names = {e["path"] for e in entries}
    assert any("results.tar.gz" in p for p in names)
    for e in entries:
        assert "size" in e
        assert "sha256" in e
        assert e["produced_by_stage"] == "test_run"
        assert e["role"] == "auxiliary"  # no hints, no spec match


def test_scan_with_hints(stage_dir):
    hints = [{"path": "results.tar.gz", "label": "推理结果", "role": "required"}]
    (stage_dir / "manifest.hints.json").write_text(json.dumps(hints))
    entries = scan_stage_dir(str(stage_dir), "test_run")
    tar_entry = [e for e in entries if "results.tar.gz" in e["path"]][0]
    assert tar_entry["role"] == "required"
    assert tar_entry["label"] == "推理结果"


def test_compute_sha256(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello")
    expected = hashlib.sha256(b"hello").hexdigest()
    assert compute_sha256(str(f)) == expected


def test_merge_manifests(tmp_path):
    m1 = [{"path": "a.txt", "sha256": "aaa", "size": 10}]
    m2 = [{"path": "b.txt", "sha256": "bbb", "size": 20}]
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /nexus/agenthub && python -m pytest harness/tests/test_evidence.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement evidence module**

```python
"""EvidenceManifest — per-stage artifact scanning and manifest generation."""

import hashlib
import json
import time
from pathlib import Path


def compute_sha256(filepath: str) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_stage_dir(stage_dir: str, stage_name: str, spec_required_paths: list[str] = None) -> list[dict]:
    """Scan a stage output directory and return manifest entries."""
    stage_path = Path(stage_dir)
    if not stage_path.exists():
        return []

    spec_required_paths = spec_required_paths or []
    # Load hints if present
    hints_map = {}
    hints_file = stage_path / "manifest.hints.json"
    if hints_file.exists():
        for h in json.loads(hints_file.read_text()):
            hints_map[h["path"]] = h

    entries = []
    for f in stage_path.iterdir():
        if f.name.startswith("manifest.hints"):
            continue
        if not f.is_file():
            continue
        rel_path = f.name
        hint = hints_map.get(rel_path, {})
        # Determine role
        role = hint.get("role", "auxiliary")
        if any(rel_path in p or p.endswith(rel_path) for p in spec_required_paths):
            role = "required"

        entries.append({
            "path": str(f),
            "size": f.stat().st_size,
            "sha256": compute_sha256(str(f)),
            "mtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(f.stat().st_mtime)),
            "produced_by_stage": stage_name,
            "role": role,
            "label": hint.get("label", ""),
            "description": hint.get("description", ""),
        })
    return entries


def merge_manifests(stage_manifests: list[dict], task_id: str, task_type: str) -> dict:
    """Merge per-stage manifests into a single evidence_manifest.json."""
    stages = []
    total_files = 0
    total_size = 0
    all_hashes = []

    for sm in stage_manifests:
        manifest_path = Path(sm["manifest_path"])
        if not manifest_path.exists():
            stages.append({"name": sm["name"], "entries": []})
            continue
        entries = json.loads(manifest_path.read_text())
        stages.append({"name": sm["name"], "entries": entries})
        total_files += len(entries)
        total_size += sum(e.get("size", 0) for e in entries)
        all_hashes.extend(e.get("sha256", "") for e in entries)

    # Compute overall manifest fingerprint
    combined = "".join(sorted(all_hashes))
    manifest_sha256 = hashlib.sha256(combined.encode()).hexdigest()

    required_count = sum(
        1 for s in stages for e in s["entries"] if e.get("role") == "required"
    )

    return {
        "task_id": task_id,
        "task_type": task_type,
        "stages": stages,
        "summary": {
            "total_files": total_files,
            "total_size_bytes": total_size,
            "required_count": required_count,
            "manifest_sha256": manifest_sha256,
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /nexus/agenthub && python -m pytest harness/tests/test_evidence.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /nexus/agenthub && git add harness/evidence.py harness/tests/test_evidence.py
git commit -m "feat(harness): add EvidenceManifest scanning and merging module"
```

---

### Task 3: Extend HarnessState

**Files:**
- Modify: `harness/orchestrator/state.py:15-31`

- [ ] **Step 1: Add new fields to HarnessState**

Add these fields after line 31 of `state.py`:

```python
    acceptance_spec: dict              # loaded AcceptanceSpec YAML as dict
    acceptance_results: dict           # {stage_id: {result, failures, metrics}}
    evidence_manifest: dict            # merged manifest (populated by final_acceptance)
    progress_log_path: str             # path to progress_log.jsonl
```

- [ ] **Step 2: Verify import still works**

Run: `cd /nexus/agenthub && python -c "from harness.orchestrator.state import HarnessState; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /nexus/agenthub && git add harness/orchestrator/state.py
git commit -m "feat(harness): extend HarnessState with acceptance/evidence/progress fields"
```

---

### Task 4: Extend ErrorHandler with ACCEPTANCE_FAILED

**Files:**
- Modify: `harness/error_handler.py`
- Modify: `harness/tests/test_error_handler.py`

- [ ] **Step 1: Write failing test**

Append to `harness/tests/test_error_handler.py`:

```python
def test_acceptance_failed(handler):
    match = handler.classify("ACCEPTANCE_FAILED: metric images_processed=1200 < 1355")
    assert match.level == "L2"
    assert match.solution == "rerun_stage"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /nexus/agenthub && python -m pytest harness/tests/test_error_handler.py::test_acceptance_failed -v`
Expected: FAIL — falls through to L3 default.

- [ ] **Step 3: Add ACCEPTANCE_FAILED pattern to knowledge.yaml**

Append to `harness/knowledge.yaml`:

```yaml
  # ── Acceptance verification failures ───────────────────────────
  - pattern: "ACCEPTANCE_FAILED"
    level: L2
    solution: "rerun_stage"
    confidence: medium
    desc: "验收检查未通过 → 诊断后单次重试该 stage"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /nexus/agenthub && python -m pytest harness/tests/test_error_handler.py -v`
Expected: All tests PASS including new one.

- [ ] **Step 5: Commit**

```bash
cd /nexus/agenthub && git add harness/knowledge.yaml harness/tests/test_error_handler.py
git commit -m "feat(harness): add ACCEPTANCE_FAILED L2 error pattern"
```

---

### Task 5: Acceptance Check Logic

**Files:**
- Create: `harness/acceptance.py`
- Test: `harness/tests/test_acceptance.py`

- [ ] **Step 1: Write failing tests**

```python
"""Tests for acceptance check logic."""
import json
from pathlib import Path

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
    entries = [{"path": str(tmp_path / "outputs/test_run/results.tar.gz"), "size": 1000, "sha256": "abc"}]
    return entries


def test_pass_all(spec, manifest_pass, tmp_path):
    metrics = {"images_processed": 1400}
    result = check_stage_acceptance("test_run", spec, manifest_pass, metrics)
    assert result["result"] == "pass"
    assert result["failures"] == []


def test_fail_missing_artifact(spec, tmp_path):
    result = check_stage_acceptance("test_run", spec, [], {})
    assert result["result"] == "fail"
    assert any(f["kind"] == "artifact_missing" for f in result["failures"])


def test_fail_metric_threshold(spec, manifest_pass):
    metrics = {"images_processed": 1200}
    result = check_stage_acceptance("test_run", spec, manifest_pass, metrics)
    assert result["result"] == "fail"
    assert any(f["kind"] == "metric" for f in result["failures"])


def test_advisory_mode_always_pass(spec, tmp_path):
    spec["acceptance_mode"] = "advisory"
    result = check_stage_acceptance("test_run", spec, [], {})
    assert result["result"] == "advisory_fail"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /nexus/agenthub && python -m pytest harness/tests/test_acceptance.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement acceptance check**

```python
"""Acceptance check — compares spec declarations against manifest facts."""

import operator
import re

OPERATORS = {
    ">=": operator.ge, "<=": operator.le,
    ">": operator.gt, "<": operator.lt,
    "==": operator.eq, "!=": operator.ne,
}


def check_stage_acceptance(
    stage_name: str,
    spec: dict,
    manifest_entries: list[dict],
    metrics: dict,
) -> dict:
    """Check a single stage against its AcceptanceSpec declarations.

    Returns: {"result": "pass"|"fail"|"advisory_fail", "failures": [...]}
    """
    stage_spec = None
    for s in spec.get("stages", []):
        if s["name"] == stage_name:
            stage_spec = s
            break
    if not stage_spec:
        return {"result": "pass", "failures": []}

    failures = []
    manifest_paths = {e.get("path", ""): e for e in manifest_entries}

    # 1. Check required artifacts
    for art in stage_spec.get("artifacts", []):
        if not art.get("required"):
            continue
        path = art["path"]
        matched = any(path in mp or mp.endswith(path) for mp in manifest_paths)
        if not matched:
            failures.append({"kind": "artifact_missing", "detail": f"Required artifact not in manifest: {path}"})
        else:
            # Check size > 0
            entry = next((e for p, e in manifest_paths.items() if path in p or p.endswith(path)), None)
            if entry and entry.get("size", 0) == 0:
                failures.append({"kind": "artifact_empty", "detail": f"Required artifact is empty: {path}"})

    # 2. Check metrics
    for m in stage_spec.get("metrics", []):
        name = m["name"]
        expect_expr = m["expect"]
        actual = metrics.get(name)
        if actual is None:
            failures.append({"kind": "metric", "detail": f"Metric '{name}' not found in metrics output"})
            continue
        if not _eval_expect(actual, expect_expr):
            failures.append({"kind": "metric", "detail": f"{name}={actual} does not satisfy {expect_expr}"})

    # Determine result
    if failures:
        if spec.get("acceptance_mode") == "advisory":
            return {"result": "advisory_fail", "failures": failures}
        return {"result": "fail", "failures": failures}
    return {"result": "pass", "failures": []}


def _eval_expect(actual, expr: str) -> bool:
    """Evaluate an expect expression like '>= 1355' against actual value."""
    match = re.match(r"(>=|<=|>|<|==|!=)\s*(.+)", expr.strip())
    if not match:
        return True  # Can't parse → pass (conservative)
    op_str, val_str = match.groups()
    op_fn = OPERATORS.get(op_str)
    if not op_fn:
        return True
    try:
        return op_fn(float(actual), float(val_str))
    except (ValueError, TypeError):
        return str(actual) == val_str
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /nexus/agenthub && python -m pytest harness/tests/test_acceptance.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /nexus/agenthub && git add harness/acceptance.py harness/tests/test_acceptance.py
git commit -m "feat(harness): add acceptance check logic with metric/artifact validation"
```

---

### Task 6: Integrate into Orchestrator Graph

**Files:**
- Modify: `harness/orchestrator/graph.py`
- Modify: `harness/orchestrator/nodes.py` (add `_collect_evidence` and `_check_acceptance` hook calls)

- [ ] **Step 1: Add hooks to graph node_fn in `graph.py`**

In `graph.py` `make_node()`, after `result = execute_stage(...)`, add evidence collection and acceptance check:

```python
# Inside node_fn, after result = execute_stage(s, state, mcp_client):
from harness.progress_log import ProgressLogger, StageStarted, StageFinished, EvidenceCollected, AcceptanceChecked
from harness.evidence import scan_stage_dir
from harness.acceptance import check_stage_acceptance
import json, time
from pathlib import Path

# Emit stage_started at top of node_fn (before execute_stage call)
log_path = state.get("progress_log_path", "outputs/progress_log.jsonl")
logger = ProgressLogger(log_path, run_id=run_id)
logger.emit(StageStarted(stage=s["id"], depends_on=s.get("depends_on", [])))

# ... execute_stage ...

# After execute_stage, collect evidence
stage_out_dir = f"outputs/{s['id']}"
spec = state.get("acceptance_spec", {})
spec_arts = []
for ss in spec.get("stages", []):
    if ss["name"] == s["id"]:
        spec_arts = [a["path"] for a in ss.get("artifacts", []) if a.get("required")]
        break
entries = scan_stage_dir(stage_out_dir, s["id"], spec_arts)
manifest_path = f"{stage_out_dir}/manifest.json"
Path(manifest_path).parent.mkdir(parents=True, exist_ok=True)
Path(manifest_path).write_text(json.dumps(entries, ensure_ascii=False, indent=2))
logger.emit(EvidenceCollected(stage=s["id"], manifest_path=manifest_path, entry_count=len(entries)))

# Check acceptance
metrics_file = Path(stage_out_dir) / "metrics.json"
metrics = json.loads(metrics_file.read_text()) if metrics_file.exists() else {}
acc_result = check_stage_acceptance(s["id"], spec, entries, metrics)
logger.emit(AcceptanceChecked(stage=s["id"], result=acc_result["result"], failures=acc_result["failures"]))

# Store acceptance result
acc_results = state.get("acceptance_results") or {}
acc_results[s["id"]] = acc_result
updates["acceptance_results"] = acc_results

# If fail and strict, raise via error string for error_handler
if acc_result["result"] == "fail":
    detail = "; ".join(f["detail"] for f in acc_result["failures"])
    updates["errors"] = [{"stage_id": s["id"], "message": f"ACCEPTANCE_FAILED: {detail}", "level": "L2"}]
    updates["report_sections"] = [{"stage_id": s["id"], "status": "FAIL", **result, "acceptance": acc_result}]

# Emit stage_finished
logger.emit(StageFinished(stage=s["id"], status=result.get("status", "unknown"), duration_sec=result.get("duration", 0)))
```

- [ ] **Step 2: Add `final_acceptance` node in `graph.py`**

After the existing `report_node`, add:

```python
def final_acceptance_node(state: HarnessState) -> dict:
    """Merge manifests, check task_assertions, emit final event."""
    import json
    from pathlib import Path
    from harness.evidence import merge_manifests
    from harness.acceptance import check_stage_acceptance
    from harness.progress_log import ProgressLogger, FinalAcceptance

    spec = state.get("acceptance_spec", {})
    test_plan = state.get("test_plan", {})
    log_path = state.get("progress_log_path", "outputs/progress_log.jsonl")
    logger = ProgressLogger(log_path)

    # Merge per-stage manifests
    stage_manifests = []
    for s in test_plan.get("stages", []):
        mp = f"outputs/{s['id']}/manifest.json"
        stage_manifests.append({"name": s["id"], "manifest_path": mp})

    merged = merge_manifests(
        stage_manifests,
        task_id=test_plan.get("name", "unknown"),
        task_type=spec.get("task_type", "unknown"),
    )
    Path("outputs/evidence_manifest.json").parent.mkdir(parents=True, exist_ok=True)
    Path("outputs/evidence_manifest.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2)
    )

    # Check task_assertions (simplified: just verify all stages passed)
    acc_results = state.get("acceptance_results", {})
    all_passed = all(r.get("result") == "pass" for r in acc_results.values())
    overall = "pass" if all_passed else "fail"

    logger.emit(FinalAcceptance(stage="__final__", overall=overall, summary=merged.get("summary", {})))

    return {"evidence_manifest": merged}

graph.add_node("final_acceptance", final_acceptance_node)
```

Wire edges: connect leaves → `final_acceptance` → `generate_report` → END.

- [ ] **Step 3: Verify import chain works**

Run: `cd /nexus/agenthub && python -c "from harness.orchestrator.graph import build_graph; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
cd /nexus/agenthub && git add harness/orchestrator/graph.py
git commit -m "feat(harness): integrate evidence/acceptance/progress into orchestrator DAG"
```

---

### Task 7: Update Report Template

**Files:**
- Modify: `harness/templates/report.md`
- Modify: `harness/reporter.py`

- [ ] **Step 1: Add three new sections to report template**

Append before the environment preservation section in the template:

```markdown
## 验收结论
{% if acceptance_results %}
| 阶段 | 结果 | 失败详情 |
|------|------|---------|
{% for stage_id, res in acceptance_results.items() %}
| {{ stage_id }} | {{ res.result | upper }} | {{ res.get('failures', []) | map(attribute='detail') | join('; ') | truncate(120) }} |
{% endfor %}
{% endif %}

## 产物清单
{% if evidence_manifest and evidence_manifest.stages %}
{% for stage in evidence_manifest.stages %}
### {{ stage.name }}
{% for entry in stage.entries %}
- `{{ entry.path }}` ({{ entry.size }} bytes, sha256: {{ entry.sha256[:12] }}...) [{{ entry.role }}]
{% endfor %}
{% endfor %}
**总计**: {{ evidence_manifest.summary.total_files }} 文件, {{ evidence_manifest.summary.total_size_bytes }} bytes
**指纹**: {{ evidence_manifest.summary.manifest_sha256[:16] }}...
{% endif %}

## 关键事件时间线
{% if progress_events %}
| 时间 | 阶段 | 事件 | 摘要 |
|------|------|------|------|
{% for ev in progress_events %}
| {{ ev.ts }} | {{ ev.stage }} | {{ ev.event_type }} | {{ ev.payload | string | truncate(80) }} |
{% endfor %}
{% endif %}
```

- [ ] **Step 2: Pass new data to template in reporter.py**

Add to `generate_report()`:

```python
acceptance_results=state.get("acceptance_results", {}),
evidence_manifest=state.get("evidence_manifest", {}),
progress_events=_load_progress_events(state.get("progress_log_path", "")),
```

Add helper:
```python
def _load_progress_events(path: str) -> list[dict]:
    """Load progress events from JSONL for report rendering."""
    if not path or not Path(path).exists():
        return []
    events = []
    for line in Path(path).read_text().strip().split("\n"):
        if line.strip():
            events.append(json.loads(line))
    return events
```

- [ ] **Step 3: Commit**

```bash
cd /nexus/agenthub && git add harness/templates/report.md harness/reporter.py
git commit -m "feat(harness): add acceptance/evidence/timeline sections to report"
```

---

### Task 8: Integration Test

**Files:**
- Create: `harness/tests/test_integration_acceptance.py`

- [ ] **Step 1: Write integration test**

```python
"""Integration test — verifies the three-piece system works end-to-end."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from harness.progress_log import ProgressLogger, StageStarted, StageFinished, EvidenceCollected, AcceptanceChecked
from harness.evidence import scan_stage_dir
from harness.acceptance import check_stage_acceptance


def test_full_stage_flow(tmp_path):
    """Simulate: stage produces files → evidence collected → acceptance checked → events logged."""
    # Setup stage output
    stage_dir = tmp_path / "outputs" / "test_run"
    stage_dir.mkdir(parents=True)
    (stage_dir / "results.tar.gz").write_bytes(b"x" * 100)
    (stage_dir / "metrics.json").write_text('{"images_processed": 1400, "failure_rate": 0.0001}')

    # Setup spec
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

    # Setup logger
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
    """Simulate: metric violation → acceptance fail."""
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
```

- [ ] **Step 2: Run all tests**

Run: `cd /nexus/agenthub && python -m pytest harness/tests/ -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
cd /nexus/agenthub && git add harness/tests/test_integration_acceptance.py
git commit -m "test(harness): add integration tests for acceptance/evidence/progress flow"
```
