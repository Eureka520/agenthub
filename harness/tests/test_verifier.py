"""Verifier unit tests."""
import json
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from harness.verifier import (
    build_verifier_prompt,
    parse_verdict,
    call_claude_verifier,
    VerifierConfig,
    build_fallback_verdict,
    run_verifier,
)


# ----- Task 2: prompt + parse -----

def test_build_prompt_includes_spec_and_manifest():
    spec = {"task_id": "t1", "stages": [{"name": "build", "artifacts": [{"path": "out.whl", "required": True}]}]}
    manifest = {"task_id": "t1", "stages": [{"name": "build", "entries": [{"path": "outputs/build/out.whl", "size": 100}]}]}
    progress_summary = "build PASS in 12s"

    prompt = build_verifier_prompt(spec, manifest, progress_summary)

    assert "AcceptanceSpec" in prompt
    assert "EvidenceManifest" in prompt
    assert "out.whl" in prompt
    assert "build PASS" in prompt
    assert "overall_verdict" in prompt


def test_parse_verdict_valid_json():
    raw = json.dumps({
        "overall_verdict": "pass",
        "checks": [{"check_id": "build.out.whl", "verdict": "pass", "evidence": "exists", "reason": "ok"}],
        "summary": "1 pass"
    })
    verdict = parse_verdict(raw)
    assert verdict["overall_verdict"] == "pass"
    assert len(verdict["checks"]) == 1


def test_parse_verdict_extracts_json_from_text():
    raw = "Here is my analysis:\n```json\n" + json.dumps({
        "overall_verdict": "fail", "checks": [], "summary": "missing"
    }) + "\n```\nDone."
    verdict = parse_verdict(raw)
    assert verdict["overall_verdict"] == "fail"


def test_parse_verdict_invalid_raises():
    with pytest.raises(ValueError):
        parse_verdict("not json at all")


# ----- Task 3: call_claude_verifier -----

def test_call_claude_invokes_correct_command():
    config = VerifierConfig(model="Claude Sonnet 4.6", timeout_sec=60, max_tokens=4096)
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = json.dumps({
        "overall_verdict": "pass", "checks": [], "summary": "ok"
    })
    fake_result.stderr = ""

    with patch("harness.verifier.subprocess.run", return_value=fake_result) as mock_run:
        verdict = call_claude_verifier("test prompt", config)

    assert verdict["overall_verdict"] == "pass"
    args = mock_run.call_args[0][0]
    assert "claude" in args[0]
    assert "-p" in args
    assert "--model" in args
    assert "Claude Sonnet 4.6" in args
    assert "--allowedTools" in args


def test_call_claude_retries_once_on_failure():
    config = VerifierConfig(model="Claude Sonnet 4.6", timeout_sec=60, retry_on_failure=True)
    fail_result = MagicMock(returncode=1, stdout="", stderr="error")
    ok_result = MagicMock(returncode=0, stdout=json.dumps({
        "overall_verdict": "pass", "checks": [], "summary": "ok"
    }), stderr="")

    with patch("harness.verifier.subprocess.run", side_effect=[fail_result, ok_result]) as mock_run:
        verdict = call_claude_verifier("test prompt", config)

    assert mock_run.call_count == 2
    assert verdict["overall_verdict"] == "pass"


def test_call_claude_raises_after_retry_exhausted():
    config = VerifierConfig(model="Claude Sonnet 4.6", timeout_sec=60, retry_on_failure=True)
    fail_result = MagicMock(returncode=1, stdout="", stderr="api error")

    with patch("harness.verifier.subprocess.run", return_value=fail_result):
        with pytest.raises(RuntimeError, match="Verifier failed"):
            call_claude_verifier("test prompt", config)


def test_call_claude_timeout_raises():
    config = VerifierConfig(model="Claude Sonnet 4.6", timeout_sec=1, retry_on_failure=False)

    with patch("harness.verifier.subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 1)):
        with pytest.raises(RuntimeError, match="timeout"):
            call_claude_verifier("test prompt", config)


# ----- Task 4: fallback -----

def test_fallback_verdict_from_phase1_pass():
    acceptance_results = {
        "build": {"result": "pass", "failures": []},
        "test": {"result": "pass", "failures": []},
    }
    verdict = build_fallback_verdict(acceptance_results, reason="cli unavailable")
    assert verdict["overall_verdict"] == "pass"
    assert verdict["fallback"] is True
    assert "cli unavailable" in verdict["fallback_reason"]
    assert len(verdict["checks"]) == 2


def test_fallback_verdict_from_phase1_fail():
    acceptance_results = {
        "build": {"result": "pass", "failures": []},
        "test": {"result": "fail", "failures": [{"kind": "metric", "detail": "acc=0.5 < 0.9"}]},
    }
    verdict = build_fallback_verdict(acceptance_results, reason="timeout")
    assert verdict["overall_verdict"] == "fail"
    fail_check = next(c for c in verdict["checks"] if c["check_id"].startswith("test"))
    assert fail_check["verdict"] == "fail"
    assert "acc=0.5" in fail_check["evidence"]


# ----- Task 5: run_verifier -----

def test_run_verifier_disabled_returns_skipped():
    state = {
        "acceptance_spec": {"verifier": {"enabled": False}},
        "evidence_manifest": {},
        "acceptance_results": {},
    }
    verdict = run_verifier(state)
    assert verdict["overall_verdict"] == "skipped"


def test_run_verifier_success_path():
    state = {
        "acceptance_spec": {
            "verifier": {"enabled": True, "model": "Claude Sonnet 4.6"},
            "stages": [{"name": "build"}],
        },
        "evidence_manifest": {"task_id": "t1", "stages": []},
        "acceptance_results": {"build": {"result": "pass", "failures": []}},
        "progress_log_path": "",
    }
    fake_result = MagicMock(returncode=0, stderr="", stdout=json.dumps({
        "overall_verdict": "pass",
        "checks": [{"check_id": "build.x", "verdict": "pass", "evidence": "y", "reason": "z"}],
        "summary": "ok"
    }))
    with patch("harness.verifier.subprocess.run", return_value=fake_result):
        verdict = run_verifier(state)
    assert verdict["overall_verdict"] == "pass"
    assert verdict.get("fallback") is False


def test_run_verifier_falls_back_when_cli_fails():
    state = {
        "acceptance_spec": {
            "verifier": {"enabled": True, "model": "Claude Sonnet 4.6", "fallback_to_phase1": True, "retry_on_failure": True},
            "stages": [],
        },
        "evidence_manifest": {"task_id": "t1", "stages": []},
        "acceptance_results": {"build": {"result": "pass", "failures": []}},
        "progress_log_path": "",
    }
    fail_result = MagicMock(returncode=1, stdout="", stderr="boom")
    with patch("harness.verifier.subprocess.run", return_value=fail_result):
        verdict = run_verifier(state)
    assert verdict["fallback"] is True
    assert verdict["overall_verdict"] == "pass"  # phase1 was pass
