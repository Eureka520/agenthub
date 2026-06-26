#!/bin/bash
# Harness gate: block MCP execution if HarnessState not initialized.
# Checks:
#   1. outputs/acceptance_spec.yaml exists and is non-empty
#   2. outputs/progress_log.jsonl exists
#   3. acceptance_spec.yaml was modified within the last 4 hours (prevent stale passthrough)

SPEC="outputs/acceptance_spec.yaml"
LOG="outputs/progress_log.jsonl"

if [ ! -s "$SPEC" ]; then
    echo '{"decision":"block","reason":"[HARNESS GATE] outputs/acceptance_spec.yaml 不存在或为空。请先完成 CHECKPOINT-1 → CHECKPOINT-2 → CHECKPOINT-3（TestPlan → AcceptanceSpec → HarnessState 初始化）后再执行 MCP 操作。"}'
    exit 0
fi

if [ ! -f "$LOG" ]; then
    echo '{"decision":"block","reason":"[HARNESS GATE] outputs/progress_log.jsonl 不存在。请先完成 CHECKPOINT-3 初始化（输出 # === HarnessState Initialized === 标记并创建 progress_log）后再执行。"}'
    exit 0
fi

# Check spec freshness: reject if older than 4 hours (stale from previous task)
SPEC_AGE=$(( $(date +%s) - $(stat -c %Y "$SPEC" 2>/dev/null || echo 0) ))
if [ "$SPEC_AGE" -gt 14400 ]; then
    echo '{"decision":"block","reason":"[HARNESS GATE] outputs/acceptance_spec.yaml 超过 4 小时未更新，可能是上次任务残留。请为当前任务重新走 CHECKPOINT-1 → 2 → 3 流程。"}'
    exit 0
fi

echo '{"decision":"allow"}'
