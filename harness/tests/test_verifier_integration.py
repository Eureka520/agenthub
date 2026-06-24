"""Verifier integration test — full graph run with mocked claude CLI."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outputs").mkdir()
    yield tmp_path


def _write_stage_artifact(stage: str, name: str, content: str):
    d = Path(f"outputs/{stage}")
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(content)


def _build_initial_state(test_plan, spec):
    return {
        "test_plan": test_plan, "current_stage": "", "completed_stages": [],
        "stage_results": {}, "environments": {}, "report_sections": [],
        "errors": [], "network_config": {}, "resolved_alternatives": {},
        "final_report": "", "acceptance_spec": spec, "acceptance_results": {},
        "evidence_manifest": {}, "progress_log_path": "outputs/progress_log.jsonl",
        "verifier_verdict": {},
    }


def test_full_graph_with_verifier_pass(workdir):
    from harness.orchestrator import graph as g

    test_plan = {
        "name": "demo",
        "goal": "smoke test",
        "stages": [
            {"id": "build", "depends_on": [], "commands": []},
        ],
    }
    spec = {
        "task_id": "demo",
        "task_type": "demo",
        "stages": [{"name": "build", "artifacts": [{"path": "out.txt", "required": True}]}],
        "verifier": {"enabled": True, "model": "Claude Sonnet 4.6", "timeout_sec": 5},
    }

    _write_stage_artifact("build", "out.txt", "hello")

    fake_verdict = {
        "overall_verdict": "pass",
        "checks": [{"check_id": "build.out.txt", "verdict": "pass", "evidence": "outputs/build/out.txt", "reason": "exists"}],
        "summary": "1 pass",
    }
    fake_run = MagicMock(returncode=0, stdout=json.dumps(fake_verdict), stderr="")
    fake_exec = MagicMock(return_value={"status": "ok", "duration": 0.1, "logs": "", "errors": []})

    with patch("harness.orchestrator.graph.execute_stage", fake_exec), \
         patch("harness.verifier.subprocess.run", return_value=fake_run):
        graph = g.build_graph(test_plan, None, run_id="test_run")
        final_state = graph.invoke(_build_initial_state(test_plan, spec))

    assert final_state["verifier_verdict"]["overall_verdict"] == "pass"
    assert Path("outputs/verifier_verdict.json").exists()
    assert "Verifier 验证结果" in final_state["final_report"]


def test_full_graph_with_verifier_fallback(workdir):
    from harness.orchestrator import graph as g

    test_plan = {
        "name": "demo",
        "stages": [{"id": "build", "depends_on": [], "commands": []}],
    }
    spec = {
        "task_id": "demo",
        "task_type": "demo",
        "stages": [{"name": "build", "artifacts": []}],
        "verifier": {"enabled": True, "model": "Claude Sonnet 4.6",
                     "timeout_sec": 1, "retry_on_failure": True, "fallback_to_phase1": True},
    }
    _write_stage_artifact("build", "x.txt", "ok")

    fail_run = MagicMock(returncode=1, stdout="", stderr="boom")
    fake_exec = MagicMock(return_value={"status": "ok", "duration": 0.1, "logs": "", "errors": []})

    with patch("harness.orchestrator.graph.execute_stage", fake_exec), \
         patch("harness.verifier.subprocess.run", return_value=fail_run):
        graph = g.build_graph(test_plan, None, run_id="test_fb")
        final_state = graph.invoke(_build_initial_state(test_plan, spec))

    v = final_state["verifier_verdict"]
    assert v.get("fallback") is True
    assert v["overall_verdict"] in ("pass", "fail")


def test_full_graph_with_verifier_disabled(workdir):
    from harness.orchestrator import graph as g

    test_plan = {
        "name": "demo",
        "stages": [{"id": "build", "depends_on": [], "commands": []}],
    }
    spec = {
        "task_id": "demo",
        "task_type": "demo",
        "stages": [{"name": "build", "artifacts": []}],
        "verifier": {"enabled": False},
    }
    _write_stage_artifact("build", "x.txt", "ok")

    fake_exec = MagicMock(return_value={"status": "ok", "duration": 0.1, "logs": "", "errors": []})

    # subprocess.run should NOT be called when verifier disabled
    with patch("harness.orchestrator.graph.execute_stage", fake_exec), \
         patch("harness.verifier.subprocess.run") as mock_run:
        graph = g.build_graph(test_plan, None, run_id="test_disabled")
        final_state = graph.invoke(_build_initial_state(test_plan, spec))
        assert mock_run.call_count == 0

    assert final_state["verifier_verdict"]["overall_verdict"] == "skipped"


def test_verifier_skipped_when_phase1_fails(workdir):
    """G2: When any stage has acceptance_results.result == 'fail', Verifier must be skipped."""
    from harness.orchestrator import graph as g
    from unittest.mock import MagicMock, patch
    import json

    test_plan = {
        "name": "demo",
        "stages": [{"id": "build", "depends_on": [], "commands": []}],
    }
    spec = {
        "task_id": "demo",
        "task_type": "demo",
        "stages": [{"name": "build", "artifacts": [{"path": "must_exist.txt", "required": True}]}],
        "verifier": {"enabled": True, "model": "Claude Sonnet 4.6"},
    }
    # Do NOT create the required artifact → Phase 1 will fail

    fake_exec = MagicMock(return_value={"status": "ok", "duration": 0.1, "logs": "", "errors": []})

    with patch("harness.orchestrator.graph.execute_stage", fake_exec), \
         patch("harness.verifier.subprocess.run") as mock_run:
        initial = {
            "test_plan": test_plan, "current_stage": "", "completed_stages": [],
            "stage_results": {}, "environments": {}, "report_sections": [],
            "errors": [], "network_config": {}, "resolved_alternatives": {},
            "final_report": "", "acceptance_spec": spec, "acceptance_results": {},
            "evidence_manifest": {}, "progress_log_path": "outputs/progress_log.jsonl",
            "verifier_verdict": {},
        }
        graph = g.build_graph(test_plan, None, run_id="test_skip")
        final_state = graph.invoke(initial)
        # subprocess.run for claude CLI must NOT be called
        assert mock_run.call_count == 0

    v = final_state["verifier_verdict"]
    assert v.get("skipped") is True
    assert v["overall_verdict"] == "fail"  # phase1 fail → fallback verdict fail


def test_verifier_verdict_path_override(workdir):
    """G4: verifier_verdict_path from state overrides default."""
    from harness.orchestrator import graph as g
    from unittest.mock import MagicMock, patch
    import json

    test_plan = {"name": "demo", "stages": [{"id": "build", "depends_on": [], "commands": []}]}
    spec = {
        "task_id": "demo", "task_type": "demo",
        "stages": [{"name": "build", "artifacts": []}],
        "verifier": {"enabled": True, "model": "Claude Sonnet 4.6"},
    }
    _write_stage_artifact("build", "x.txt", "ok")

    fake_verdict = {"overall_verdict": "pass", "checks": [], "summary": "ok"}
    fake_run = MagicMock(returncode=0, stdout=json.dumps(fake_verdict), stderr="")
    fake_exec = MagicMock(return_value={"status": "ok", "duration": 0.1, "logs": "", "errors": []})

    custom_path = "custom_outputs/my_verdict.json"
    with patch("harness.orchestrator.graph.execute_stage", fake_exec), \
         patch("harness.verifier.subprocess.run", return_value=fake_run):
        initial = {
            "test_plan": test_plan, "current_stage": "", "completed_stages": [],
            "stage_results": {}, "environments": {}, "report_sections": [],
            "errors": [], "network_config": {}, "resolved_alternatives": {},
            "final_report": "", "acceptance_spec": spec, "acceptance_results": {},
            "evidence_manifest": {}, "progress_log_path": "outputs/progress_log.jsonl",
            "verifier_verdict": {}, "verifier_verdict_path": custom_path,
        }
        graph = g.build_graph(test_plan, None, run_id="test_path")
        graph.invoke(initial)

    from pathlib import Path
    assert Path(custom_path).exists()
