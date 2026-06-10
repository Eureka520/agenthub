"""HarnessState — the shared state passed through LangGraph nodes."""

from typing import TypedDict, Annotated
from operator import add


class StageResult(TypedDict, total=False):
    status: str       # "ok", "fail", "timeout", "skipped"
    duration: float
    logs: str
    errors: list[dict]
    commands_run: list[str]


class HarnessState(TypedDict, total=False):
    test_plan: dict
    current_stage: str
    completed_stages: Annotated[list[str], add]
    stage_results: dict        # {stage_id: StageResult}
    environments: dict         # {env_id: {container_name, venv_path, status, can_reenter}}
    report_sections: Annotated[list[dict], add]
    errors: Annotated[list[dict], add]
    network_config: dict
    resolved_alternatives: dict  # {stage_id: "main" | "alt_0"}
    gpu_device: str            # selected GPU ID (e.g. "3")
    gpu_monitor_log: str       # path to nvidia-smi dmon log
    final_report: str
    execution_mode: str        # "graph_invoke" | "manual_orchestration"
    degradation_reason: str    # empty if normal execution
    issues_resolved: Annotated[list[dict], add]   # [{stage, problem, solution, knowledge_updated}]
    knowledge_updates: Annotated[list[dict], add]  # [{target_file, section, summary, status}]
