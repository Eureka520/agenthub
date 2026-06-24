"""Report generator — renders HarnessState into markdown report."""

import json
import time
from pathlib import Path
from typing import Optional

from jinja2 import Template

TEMPLATE_PATH = Path(__file__).parent / "templates" / "report.md"


def generate_report(state: dict, output_path: Optional[str] = None) -> str:
    """Generate markdown report from HarnessState."""
    template_str = TEMPLATE_PATH.read_text() if TEMPLATE_PATH.exists() else DEFAULT_TEMPLATE
    template = Template(template_str)

    test_plan = state.get("test_plan", {})
    report = template.render(
        name=test_plan.get("name", "Unknown"),
        goal=test_plan.get("goal", ""),
        source_doc=test_plan.get("source_doc", ""),
        timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
        environments=state.get("environments", {}),
        stage_results=state.get("stage_results", {}),
        report_sections=state.get("report_sections", []),
        errors=state.get("errors", []),
        resolved_alternatives=state.get("resolved_alternatives", {}),
        gpu_device=state.get("gpu_device", ""),
        gpu_monitor_log=state.get("gpu_monitor_log", ""),
        total_status=_compute_status(state),
        execution_mode=state.get("execution_mode", "graph_invoke"),
        degradation_reason=state.get("degradation_reason", ""),
        issues_resolved=state.get("issues_resolved", []),
        knowledge_updates=state.get("knowledge_updates", []),
        acceptance_results=state.get("acceptance_results", {}),
        evidence_manifest=state.get("evidence_manifest", {}),
        progress_events=_load_progress_events(state.get("progress_log_path", "")),
        verifier_verdict=state.get("verifier_verdict", {}),
    )

    if output_path:
        Path(output_path).write_text(report)
    return report


def _compute_status(state: dict) -> str:
    results = state.get("stage_results", {})
    if not results:
        return "NOT_STARTED"
    statuses = [r.get("status") for r in results.values()]
    if all(s == "ok" for s in statuses):
        return "PASS"
    if any(s == "ok" for s in statuses):
        return "PARTIAL"
    return "FAIL"


def _load_progress_events(path: str) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    events = []
    for line in Path(path).read_text().strip().split("\n"):
        if line.strip():
            events.append(json.loads(line))
    return events


DEFAULT_TEMPLATE = """# 测试报告: {{ name }}

## 基本信息
- 目标: {{ goal }}
- 提测文档: {{ source_doc }}
- 执行时间: {{ timestamp }}
- 总状态: {{ total_status }}

## 各阶段详情
{% for section in report_sections %}
### {{ section.stage_id }}
- 状态: {{ section.status }}
- 耗时: {{ section.get('duration', 'N/A') }}s
{% if section.get('errors') %}
- 错误: {{ section.errors[0].get('message', '') | truncate(200) }}
{% endif %}
{% endfor %}

## 验收结论
{% if acceptance_results %}
| 阶段 | 结果 | 失败详情 |
|------|------|---------|
{% for stage_id, res in acceptance_results.items() %}
| {{ stage_id }} | {{ res.result | upper }} | {{ res.get('failures', []) | map(attribute='detail') | join('; ') | truncate(120) }} |
{% endfor %}
{% else %}
未配置验收规格。
{% endif %}

## Verifier 验证结果
{% if verifier_verdict and verifier_verdict.get('overall_verdict') %}
**总判定**: {{ verifier_verdict.overall_verdict | upper }}{% if verifier_verdict.get('fallback') %} _(降级：{{ verifier_verdict.get('fallback_reason','') | truncate(100) }})_{% endif %}
**模型**: {{ verifier_verdict.get('model_used', 'N/A') }}
**摘要**: {{ verifier_verdict.get('summary', '') }}

| Check | 判定 | 证据 | 理由 |
|-------|------|------|------|
{% for c in verifier_verdict.get('checks', []) %}
| {{ c.check_id }} | {% if c.verdict == 'needs_review' %}**[NEEDS_REVIEW]**{% else %}{{ c.verdict | upper }}{% endif %} | {{ c.evidence | truncate(80) }} | {{ c.reason | truncate(80) }} |
{% endfor %}
{% else %}
未运行 Verifier。
{% endif %}

## 产物清单
{% if evidence_manifest and evidence_manifest.stages %}
{% for stage in evidence_manifest.stages %}
### {{ stage.name }}
{% for entry in stage.entries %}
- `{{ entry.path }}` ({{ entry.size }} bytes, sha256: {{ entry.sha256[:12] }}...) [{{ entry.role }}]
{% endfor %}
{% endfor %}
**总计**: {{ evidence_manifest.summary.total_files }} 文件, {{ evidence_manifest.summary.total_size_bytes }} bytes
**指纹**: {{ evidence_manifest.summary.manifest_sha256[:16] }}...
{% else %}
无产物记录。
{% endif %}

## 关键事件时间线
{% if progress_events %}
| 时间 | 阶段 | 事件 | 摘要 |
|------|------|------|------|
{% for ev in progress_events %}
| {{ ev.ts }} | {{ ev.stage }} | {{ ev.event_type }} | {{ ev.payload | string | truncate(80) }} |
{% endfor %}
{% else %}
无事件记录。
{% endif %}

## 异常汇总
{% if errors %}
| 阶段 | 级别 | 错误摘要 |
|------|------|---------|
{% for err in errors %}
| {{ err.get('stage_id', '') }} | {{ err.get('level', 'L3') }} | {{ err.get('message', '') | truncate(100) }} |
{% endfor %}
{% else %}
无异常。
{% endif %}

## 环境保留信息
{% for env_id, info in environments.items() %}
- {{ env_id }}: {% if info.get('container_name') %}`docker exec -it {{ info.container_name }} bash`{% elif info.get('venv_path') %}`source {{ info.venv_path }}/bin/activate`{% endif %}
{% endfor %}
"""
