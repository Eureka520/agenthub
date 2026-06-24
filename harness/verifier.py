"""Verifier — independent judge using Claude CLI in non-interactive mode.

Provides a physically isolated second opinion on whether the Worker's output
satisfies the AcceptanceSpec. Uses `claude -p --allowedTools Read,Glob,Grep`
so the verifier cannot modify any file.
"""

import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path


PROMPT_TEMPLATE = """You are an independent verifier. Your job is to judge whether the Worker's execution result satisfies the AcceptanceSpec.

You are physically isolated from the execution: you have ONLY read-only tools (Read, Glob, Grep). You CANNOT modify any file.

## AcceptanceSpec
```json
{spec_json}
```

## EvidenceManifest (artifacts produced by Worker)
```json
{manifest_json}
```

## ProgressLog Summary
{progress_summary}

## Your Task
For each declaration in AcceptanceSpec, give an itemized verdict. Use Read/Glob/Grep to verify the actual file contents when needed. Then output your final judgment as a SINGLE JSON object matching this schema:

```json
{{
  "overall_verdict": "pass | fail | needs_review",
  "checks": [
    {{
      "check_id": "<stage>.<artifact-or-metric-id>",
      "verdict": "pass | fail | needs_review",
      "evidence": "<concrete evidence: path + key content>",
      "reason": "<why this verdict>"
    }}
  ],
  "summary": "<one-line summary>"
}}
```

Output the JSON object as your final message, wrapped in a ```json code block. Do not output anything after the JSON.
"""


def build_verifier_prompt(spec: dict, manifest: dict, progress_summary: str) -> str:
    return PROMPT_TEMPLATE.format(
        spec_json=json.dumps(spec, ensure_ascii=False, indent=2),
        manifest_json=json.dumps(manifest, ensure_ascii=False, indent=2),
        progress_summary=progress_summary or "(no events)",
    )


def parse_verdict(raw_output: str) -> dict:
    """Extract verdict JSON from Claude CLI output."""
    text = raw_output.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))

    match = re.search(r"(\{[^{]*\"overall_verdict\".*\})", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
        

    raise ValueError(f"No valid verdict JSON found in output: {text[:200]}")


@dataclass
class VerifierConfig:
    model: str = "Claude Sonnet 4.6"
    max_tokens: int = 4096
    timeout_sec: int = 60
    retry_on_failure: bool = True
    fallback_to_phase1: bool = True
    allowed_tools: list = field(default_factory=lambda: ["Read", "Glob", "Grep"])
    extra_args: list = field(default_factory=list)


def call_claude_verifier(prompt: str, config: VerifierConfig) -> dict:
    """Spawn `claude -p` with read-only tools and parse verdict.

    Raises:
        RuntimeError: if CLI fails after retry, times out, or output unparsable.
    """
    cmd = [
        "claude",
        "-p",
        "--model", config.model,
        "--output-format", "text",
        "--allowedTools", ",".join(config.allowed_tools),
        *config.extra_args,
    ]

    attempts = 2 if config.retry_on_failure else 1
    last_err = ""
    for attempt in range(attempts):
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=config.timeout_sec,
            )
        except subprocess.TimeoutExpired as e:
            last_err = f"timeout after {config.timeout_sec}s"
            if attempt == attempts - 1:
                raise RuntimeError(f"Verifier {last_err}") from e
            continue

        if result.returncode != 0:
            last_err = f"exit={result.returncode} stderr={result.stderr[:200]}"
            if attempt == attempts - 1:
                raise RuntimeError(f"Verifier failed: {last_err}")
            continue

        try:
            return parse_verdict(result.stdout)
        except ValueError as e:
            last_err = f"unparsable output: {e}"
            if attempt == attempts - 1:
                raise RuntimeError(f"Verifier failed: {last_err}") from e
            continue

    raise RuntimeError(f"Verifier failed: {last_err}")


def build_fallback_verdict(acceptance_results: dict, reason: str) -> dict:
    """Construct a verdict from Phase 1 rule-based results when Verifier unavailable."""
    checks = []
    any_fail = False
    for stage_id, res in acceptance_results.items():
        result = res.get("result", "pass")
        failures = res.get("failures", [])
        if result == "fail":
            any_fail = True
            evidence = "; ".join(f.get("detail", "") for f in failures)
        else:
            evidence = "Phase 1 rules passed"
        checks.append({
            "check_id": f"{stage_id}.phase1",
            "verdict": "fail" if result == "fail" else ("needs_review" if result == "advisory_fail" else "pass"),
            "evidence": evidence,
            "reason": "rule-engine fallback",
        })
    return {
        "overall_verdict": "fail" if any_fail else "pass",
        "checks": checks,
        "summary": f"fallback: {len(checks)} stages, {sum(1 for c in checks if c['verdict']=='fail')} failed",
        "fallback": True,
        "fallback_reason": reason,
    }


def _summarize_progress_log(path: str, max_events: int = 30) -> str:
    if not path or not Path(path).exists():
        return "(no progress log)"
    lines = Path(path).read_text().strip().split("\n")
    if not lines or lines == [""]:
        return "(empty log)"
    out = []
    for line in lines[-max_events:]:
        try:
            ev = json.loads(line)
            out.append(f"[{ev.get('event_type','?')}] {ev.get('stage','?')} {json.dumps(ev.get('payload',{}), ensure_ascii=False)[:120]}")
        except json.JSONDecodeError:
            continue
    return "\n".join(out)


def run_verifier(state: dict) -> dict:
    """Top-level Verifier orchestration. Returns a verdict dict.

    Reads from state:
      - acceptance_spec.verifier (config)
      - evidence_manifest (Worker output)
      - acceptance_results (Phase 1 conclusions)
      - progress_log_path
    """
    spec = state.get("acceptance_spec") or {}
    vcfg = spec.get("verifier") or {}
    if not vcfg.get("enabled", True):
        return {"overall_verdict": "skipped", "checks": [], "summary": "verifier disabled"}

    config = VerifierConfig(
        model=vcfg.get("model", "Claude Sonnet 4.6"),
        max_tokens=vcfg.get("max_tokens", 4096),
        timeout_sec=vcfg.get("timeout_sec", 60),
        retry_on_failure=vcfg.get("retry_on_failure", True),
        fallback_to_phase1=vcfg.get("fallback_to_phase1", True),
    )

    manifest = state.get("evidence_manifest") or {}
    progress_summary = _summarize_progress_log(state.get("progress_log_path", ""))
    prompt = build_verifier_prompt(spec, manifest, progress_summary)

    t0 = time.time()
    try:
        verdict = call_claude_verifier(prompt, config)
        verdict["model_used"] = config.model
        verdict["duration_ms"] = int((time.time() - t0) * 1000)
        verdict["fallback"] = False
        return verdict
    except RuntimeError as e:
        if config.fallback_to_phase1:
            return build_fallback_verdict(state.get("acceptance_results") or {}, reason=str(e))
        raise
