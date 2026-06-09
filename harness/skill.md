# Test Harness Skill

当用户要求执行提测任务时，调用此 skill。

## 触发条件

用户提供了提测文档（.md 文件）并要求执行测试。

## 执行流程

1. **解析文档**: `python -m harness parse <doc.md>` 生成 TestPlan
2. **检查硬件**: 调用 `system_info()` 确认可用 MCP 节点
3. **执行测试**: `python -m harness run <doc.md>` 或通过 LangGraph 逐步执行
4. **输出报告**: 生成 markdown 格式测试报告

## 约束规则（必须遵守）

1. 执行前必须 `system_info()` 确认硬件匹配
2. 只在 TestPlan 中 `mcp_node != null` 的硬件上执行，其余标记 skip
3. 每步执行后运行 verify 命令，失败则不进下一步
4. `service_start` 类型强制 nohup 后台 + health_check，不可跳过
5. 遇到 L3 错误立即停止，输出到当前的报告
6. 不修改提测文档中不确定的代码（如占位符路径），只记录到报告
7. 不伪造执行结果，不编造输出数据
8. 环境执行完不删除，报告中给出再进入方式
9. 安装类操作遵循 `harness/config.yaml` 代理切换策略
10. 遇到错误先查 `harness/knowledge.yaml`，匹配已知模式则按方案处理
11. 当用户教你解决了测试执行中的错误时，必须将 pattern + solution 写入 `harness/knowledge.yaml`（格式参考已有条目，confidence 设为 medium）
12. install/service_start/test_run 必须在 docker 容器或 venv 中执行，禁止直接操作宿主机。生成 TestPlan 时，pip install、服务启动、测试脚本必须归类为 install/service_start/test_run 类型（不要归为 custom），确保宿主机保护生效

## 错误处理

- L1（自动修复）: 网络超时→换代理、缺模块→pip install
- L2（尝试修复）: OOM→降参数、版本冲突→尝试替代版本
- L3（停止记录）: segfault、被 kill → 完整记录 stderr，保留环境

## 报告要求

每次执行必须产出报告，即使中途失败也要报告到失败点为止。
