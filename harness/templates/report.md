# 测试报告: {{ name }}

## 基本信息
- 目标: {{ goal }}
- 提测文档: {{ source_doc }}
- 执行时间: {{ timestamp }}
- 总状态: {{ total_status }}
- GPU 设备: {{ gpu_device | default('N/A') }}

## 执行模式
- 模式: {{ execution_mode | default('graph_invoke') }}
{% if degradation_reason %}- 降级原因: {{ degradation_reason }}
{% endif %}

## 各阶段详情
{% for section in report_sections %}
### {{ section.stage_id }}
- 状态: {{ section.status }}
- 耗时: {{ section.get('duration', 'N/A') }}s
{% if section.get('errors') %}
- 错误: {{ section.errors[0].get('message', '') | truncate(200) }}
{% endif %}
{% if section.get('commands_run') %}
- 执行命令:
{% for cmd in section.commands_run %}
  - `{{ cmd.get('cmd', '') }}` → {{ cmd.get('status', '') }}
{% endfor %}
{% endif %}
{% endfor %}

## GPU/CPU 资源监控
- 监控日志: {{ gpu_monitor_log | default('未记录') }}
{% if gpu_device %}
- 使用 GPU: {{ gpu_device }}
- 所有命令通过 CUDA_VISIBLE_DEVICES={{ gpu_device }} 锁定
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
- {{ env_id }}: {% if info.get('container_name') %}`docker exec -it {{ info.container_name }} bash`{% elif info.get('venv_path') %}`source {{ info.venv_path }}/bin/activate`{% endif %} (GPU: {{ info.get('gpu_device', 'all') }})
{% endfor %}

## 备选方案选择
{% for stage_id, choice in resolved_alternatives.items() %}
- {{ stage_id }}: {{ choice }}
{% endfor %}

## 问题与解决
{% if issues_resolved %}
| 阶段 | 问题 | 解决方案 | 知识库已更新 |
|------|------|----------|-------------|
{% for issue in issues_resolved %}| {{ issue.get('stage', '') }} | {{ issue.get('problem', '') }} | {{ issue.get('solution', '') }} | {{ issue.get('knowledge_updated', '否') }} |
{% endfor %}{% else %}
无异常。
{% endif %}

## 知识库更新
{% if knowledge_updates %}
| 目标文件 | Section | 内容摘要 | 状态 |
|----------|---------|----------|------|
{% for update in knowledge_updates %}| {{ update.get('target_file', '') }} | {{ update.get('section', '') }} | {{ update.get('summary', '') }} | {{ update.get('status', '') }} |
{% endfor %}{% else %}
本次执行无新增知识。
{% endif %}
