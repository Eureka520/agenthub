"""LangGraph dynamic graph builder — constructs DAG from TestPlan stages."""

import json
import time
from pathlib import Path
from typing import Any

from langgraph.graph import StateGraph, END

from harness.orchestrator.state import HarnessState
from harness.orchestrator.nodes import execute_stage, McpClient
from harness.orchestrator.checkpoint import FileCheckpoint
from harness.progress_log import (
    ProgressLogger, StageStarted, StageFinished,
    EvidenceCollected, AcceptanceChecked, ErrorRaised, FinalAcceptance,
)
from harness.evidence import scan_stage_dir, merge_manifests
from harness.acceptance import check_stage_acceptance


def build_graph(test_plan: dict, mcp: McpClient = None, run_id: str = "") -> StateGraph:
    """Build a LangGraph from TestPlan stages and their dependencies."""
    stages = test_plan.get("stages", [])
    if not stages:
        raise ValueError("TestPlan has no stages")

    graph = StateGraph(HarnessState)
    stage_ids = {s["id"] for s in stages}
    mcp_client = mcp or McpClient()

    # Add a node for each stage
    for stage in stages:
        def make_node(s=stage):
            def node_fn(state: HarnessState) -> dict:
                # Skip if already completed (resume scenario)
                if s["id"] in (state.get("completed_stages") or []):
                    return {}

                log_path = state.get("progress_log_path", "outputs/progress_log.jsonl")
                logger = ProgressLogger(log_path, run_id=run_id)

                # Emit stage_started
                logger.emit(StageStarted(stage=s["id"], depends_on=s.get("depends_on", [])))

                state["current_stage"] = s["id"]
                result = execute_stage(s, state, mcp_client)

                # Update state
                stage_results = state.get("stage_results") or {}
                stage_results[s["id"]] = result
                updates = {"stage_results": stage_results, "current_stage": s["id"]}

                if result.get("status") == "ok":
                    updates["completed_stages"] = [s["id"]]
                    updates["report_sections"] = [{"stage_id": s["id"], "status": "PASS", **result}]
                else:
                    updates["errors"] = [{"stage_id": s["id"], **result}]
                    updates["report_sections"] = [{"stage_id": s["id"], "status": "FAIL", **result}]

                # Collect evidence
                stage_out_dir = f"outputs/{s['id']}"
                spec = state.get("acceptance_spec") or {}
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

                acc_results = state.get("acceptance_results") or {}
                acc_results[s["id"]] = acc_result
                updates["acceptance_results"] = acc_results

                # If acceptance failed (strict mode)
                if acc_result["result"] == "fail":
                    detail = "; ".join(f["detail"] for f in acc_result["failures"])
                    logger.emit(ErrorRaised(stage=s["id"], error_code="ACCEPTANCE_FAILED", level="L2", match_pattern=""))
                    updates["errors"] = [{"stage_id": s["id"], "message": f"ACCEPTANCE_FAILED: {detail}", "level": "L2"}]
                    updates["report_sections"] = [{"stage_id": s["id"], "status": "FAIL", **result, "acceptance": acc_result}]

                # Emit stage_finished
                logger.emit(StageFinished(stage=s["id"], status=result.get("status", "unknown"), duration_sec=result.get("duration", 0)))
                return updates
            return node_fn

        graph.add_node(stage["id"], make_node())

    # Add final_acceptance node
    def final_acceptance_node(state: HarnessState) -> dict:
        spec = state.get("acceptance_spec") or {}
        test_plan_data = state.get("test_plan", {})
        log_path = state.get("progress_log_path", "outputs/progress_log.jsonl")
        logger = ProgressLogger(log_path, run_id=run_id)

        stage_manifests = []
        for s in test_plan_data.get("stages", []):
            mp = f"outputs/{s['id']}/manifest.json"
            stage_manifests.append({"name": s["id"], "manifest_path": mp})

        merged = merge_manifests(
            stage_manifests,
            task_id=test_plan_data.get("name", "unknown"),
            task_type=spec.get("task_type", "unknown"),
        )
        Path("outputs/evidence_manifest.json").parent.mkdir(parents=True, exist_ok=True)
        Path("outputs/evidence_manifest.json").write_text(json.dumps(merged, ensure_ascii=False, indent=2))

        acc_results = state.get("acceptance_results") or {}
        all_passed = all(r.get("result") in ("pass", "advisory_fail") for r in acc_results.values())
        overall = "pass" if all_passed else "fail"

        logger.emit(FinalAcceptance(stage="__final__", overall=overall, summary=merged.get("summary", {})))
        return {"evidence_manifest": merged}

    graph.add_node("final_acceptance", final_acceptance_node)

    # Add verifier node — independent judge with read-only tool schema
    def verifier_node(state: HarnessState) -> dict:
        from harness.verifier import run_verifier, build_fallback_verdict

        log_path = state.get("progress_log_path") or "outputs/progress_log.jsonl"
        logger = ProgressLogger(log_path, run_id=run_id)

        # G2: If Phase 1 already failed, skip Verifier (per spec section 13)
        acc_results = state.get("acceptance_results") or {}
        phase1_failed = any(r.get("result") == "fail" for r in acc_results.values())
        if phase1_failed:
            verdict = build_fallback_verdict(acc_results, reason="phase1_failed: Verifier skipped")
            verdict["skipped"] = True
        else:
            try:
                verdict = run_verifier(state)
            except Exception as e:
                verdict = {
                    "overall_verdict": "needs_review",
                    "checks": [],
                    "summary": f"verifier crashed: {e}",
                    "fallback": True,
                    "fallback_reason": f"exception: {e}",
                }

        failures = [
            {"kind": "verifier", "detail": f"{c['check_id']}: {c.get('reason','')}"}
            for c in verdict.get("checks", [])
            if c.get("verdict") in ("fail", "needs_review")
        ]
        logger.emit(AcceptanceChecked(
            stage="__verifier__",
            result=verdict.get("overall_verdict", "needs_review"),
            failures=failures,
        ))

        # G4: Resolve verdict path from state (fall back to relative outputs/)
        verdict_path = Path(state.get("verifier_verdict_path") or "outputs/verifier_verdict.json")
        verdict_path.parent.mkdir(parents=True, exist_ok=True)
        verdict_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2))

        return {"verifier_verdict": verdict}

    graph.add_node("verifier", verifier_node)

    # Add report node
    def report_node(state: HarnessState) -> dict:
        from harness.reporter import generate_report
        report = generate_report(state)
        return {"final_report": report}

    graph.add_node("generate_report", report_node)

    # Add edges based on depends_on
    roots = []
    for stage in stages:
        deps = stage.get("depends_on", [])
        if not deps:
            roots.append(stage["id"])
        else:
            for dep in deps:
                if dep in stage_ids:
                    graph.add_edge(dep, stage["id"])

    # Connect start to root nodes
    if len(roots) == 1:
        graph.set_entry_point(roots[0])
    else:
        graph.set_entry_point(roots[0])
        for root in roots[1:]:
            graph.add_edge("__start__", root)

    # Connect leaf nodes → final_acceptance → report → END
    has_outgoing = set()
    for stage in stages:
        for dep in stage.get("depends_on", []):
            has_outgoing.add(dep)
    leaves = [s["id"] for s in stages if s["id"] not in has_outgoing]
    for leaf in leaves:
        graph.add_edge(leaf, "final_acceptance")

    graph.add_edge("final_acceptance", "verifier")
    graph.add_edge("verifier", "generate_report")
    graph.add_edge("generate_report", END)

    return graph.compile()


def run_harness(test_plan: dict, mcp: McpClient = None, run_id: str = None) -> dict:
    """Execute a full harness run."""
    run_id = run_id or f"run_{int(time.time())}"
    checkpoint = FileCheckpoint(run_id)

    # Initialize state
    initial_state = checkpoint.load() or {
        "test_plan": test_plan,
        "current_stage": "",
        "completed_stages": [],
        "stage_results": {},
        "environments": {},
        "report_sections": [],
        "errors": [],
        "network_config": {},
        "resolved_alternatives": {},
        "final_report": "",
        "acceptance_spec": {},
        "acceptance_results": {},
        "evidence_manifest": {},
        "progress_log_path": "outputs/progress_log.jsonl",
        "verifier_verdict": {},
    }

    graph = build_graph(test_plan, mcp, run_id=run_id)
    final_state = graph.invoke(initial_state)

    # Save final checkpoint
    checkpoint.save(final_state)
    return final_state
