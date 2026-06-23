"""ProgressLog — append-only JSONL audit trail for harness decisions."""

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path


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
    result: str
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
    stage: str
    overall: str
    summary: dict = field(default_factory=dict)
    _event_type: str = field(default="final_acceptance", init=False)


class ProgressLogger:
    """Append-only JSONL logger for harness events."""

    def __init__(self, path: str, run_id: str = ""):
        self.path = path
        self.run_id = run_id or f"run_{int(time.time())}"
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event) -> None:
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
