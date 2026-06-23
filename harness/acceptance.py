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
    match = re.match(r"(>=|<=|>|<|==|!=)\s*(.+)", expr.strip())
    if not match:
        return True
    op_str, val_str = match.groups()
    op_fn = OPERATORS.get(op_str)
    if not op_fn:
        return True
    try:
        return op_fn(float(actual), float(val_str))
    except (ValueError, TypeError):
        return str(actual) == val_str
