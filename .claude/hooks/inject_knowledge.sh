#!/bin/bash
# PreToolUse hook: inject priors and config into agent context before MCP calls.
# Ensures agent sees relevant knowledge even if it forgot to read it.

echo ""
echo "=== [HARNESS PRE-EXEC REMINDER] ==="
echo "确认：本次操作是否符合以下已知最佳实践？"
echo ""
echo "[PRIORS — 相关领域推荐做法]"
cat knowledge/priors.yaml 2>/dev/null
echo ""
echo "[KNOWN ISSUES — 如遇错误先匹配此表]"
cat harness/knowledge.yaml 2>/dev/null
echo ""
echo "=== [/HARNESS PRE-EXEC REMINDER] ==="
