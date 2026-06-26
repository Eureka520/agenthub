#!/bin/bash
# PostToolUse hook: on error, inject knowledge.yaml for pattern matching.
# Also reminds agent to output CHECKPOINT-4 after stage completion.

INPUT=$(cat)
EXIT_CODE=$(echo "$INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_result',{}).get('exit_code',0))" 2>/dev/null)

if [ "$EXIT_CODE" != "0" ]; then
    echo ""
    echo "=== [ERROR DETECTED — 先查已知问题再行动] ==="
    echo "[KNOWN ISSUES]"
    cat harness/knowledge.yaml 2>/dev/null
    echo ""
    echo "规则：未知错误不猜测解决方案，记录完整 stderr 并停止。"
    echo "=== [/ERROR DETECTED] ==="
fi

echo ""
echo "[POST-EXEC REMINDER] 如果当前 stage 已完成，请立刻输出 CHECKPOINT-4 自检块。"
