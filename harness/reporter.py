"""Report generator — renders HarnessState into markdown report."""

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
