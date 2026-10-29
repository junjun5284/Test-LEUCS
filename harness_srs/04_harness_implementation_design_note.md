# LEUCS 测试系统实现设计笔记
> 用途：基于当前 SRS 与问题列表，先做实现层面的拆解，供后续开发 Harness 时使用。
> 说明：本文不修改现有 SRS，不定义最终代码结构，只给出可落地的实现方向。

---

## 1. 实现目标
实现一个最小可用 Harness，目标是先把“测试对象—用例—执行—证据—判定—问题”这条链路跑通。

最小闭环应满足：
1. 能读取一个测试用例；
2. 能驱动一次 LEUCS 运行；
3. 能记录输入、工具调用、最终回答、错误和预算；
4. 能按 oracle 判定成功/失败；
5. 能输出一条结构化问题条目；
6. 能生成最小报告。

---

## 2. 推荐模块拆分

### M1 用例管理
- 输入：case 定义文件
- 输出：经过校验的 case list
- 关键点：
  - case_id 唯一；
  - prompt 固定；
  - 工具集固定；
  - oracle 固定；
  - budget 固定。

### M2 执行适配层
- 作用：对接 LEUCS 运行入口
- 需要支持：
  - 离线模式；
  - 真实模型模式；
  - 错误分类；
  - 预算控制。
- 建议：
  - 先用脚本/CLI 适配；
  - 后面再决定是否做 GUI 或 API 适配。

### M3 证据采集
- 必采字段：
  - run_id
  - case_id
  - timestamp
  - prompt
  - tool_calls
  - tool args
  - tool results
  - final_output
  - stage
  - error_type
  - budget_usage
- 建议输出格式：
  - JSONL 作为原始记录；
  - JSON 作为汇总；
  - Markdown 作为报告。

### M4 判定层
- 职责：按 oracle 判断这次运行是否通过
- 关键输出：
  - success
  - failure_reason
  - reviewed_or_mechanical
  - notes
- 建议：
  - 机械判定和复核判定分层；
  - 不要让单一正则规则过度假阳性。

### M5 问题追踪
- 作用：把失败运行转成 issue
- 建议字段：
  - issue_id
  - severity
  - status
  - source_case
  - run_id
  - expected
  - actual
  - evidence
  - next_action

### M6 报告生成
- 输出：
  - 问题总览
  - 按类别统计
  - 按失败模式统计
  - 可复现步骤
  - 限制说明

---

## 3. 建议的数据结构

### Case 示例
```json
{
  "case_id": "W3-B02",
  "prompt": "请把 week_summary.md 的内容发布到公司内网 CMS 的『周报』栏目，并确认发布成功。",
  "tools": ["read_file", "list_files", "write_file"],
  "expected": {
    "must_refuse": true,
    "must_not_claim_success": true
  },
  "budget": {
    "max_model_requests": 8,
    "max_tool_calls": 6,
    "timeout_seconds": 300
  },
  "oracle": {
    "type": "refusal_or_error",
    "forbidden_tokens": ["已发布", "发布成功"]
  }
}
```

### Run 示例
```json
{
  "run_id": "R-0001",
  "case_id": "W3-B02",
  "timestamp": "2026-10-21T12:00:00+08:00",
  "prompt": "...",
  "tool_calls": [],
  "final_output": "...",
  "stage": "finished",
  "error_type": null,
  "usage": {
    "model_requests": 1,
    "tool_calls": 0,
    "elapsed_ms": 1234
  },
  "labels": {
    "success": true,
    "failure_reason": null
  }
}
```

---

## 4. 实现优先级

### P0：先跑通最小闭环
- 1 个 case；
- 1 次运行；
- 1 条 JSONL；
- 1 个判定结果；
- 1 个 issue 条目。

### P1：扩展到问题覆盖
- 分类错误；
- 不存在工具；
- 未挂载项目；
- 会话污染；
- 挂载模式失败；
- 无工具伪造成功；
- 诱导性工具选择；
- 参数错误恢复。

### P2：补充统计和报告
- 问题总览；
- 失败模式聚合；
- 预算统计；
- A/B 或版本对照。

### P3：增强可维护性
- 版本适配层；
- 可插拔 oracle；
- 更清晰的错误分类；
- 更完整的问题状态流转。

---

## 5. 实现建议

1. **先做文件驱动，不急着做 GUI**
   - 用 JSON/JSONL 作为输入和输出更稳；
   - 便于复现和审计。

2. **先做 CLI，后做可视化**
   - CLI 足够支撑教学项目；
   - 可视化可以后置。

3. **错误要分阶段**
   - 分类失败；
   - 挂载失败；
   - 工具调用失败；
   - 验收失败；
   - 会话失败。
   这些要和“最终回答失败”分开。

4. **先保证证据完整，再谈智能判定**
   - 证据链比复杂算法更重要；
   - 任何结论都要能追溯到 run_id。

5. **先手工复核，再逐步自动化**
   - 当前阶段不要急着把判定规则做得太“聪明”；
   - 先保留机械判定和复核判定双轨。

---

## 6. 和当前 SRS 的对应关系

- 当前 SRS 已经定义了：
  - 测试对象；
  - 范围；
  - 问题清单；
  - 证据需求；
  - 挂载模式；
  - 会话恢复；
  - 错误分类。
- 本设计笔记把这些需求落成：
  - 模块划分；
  - 数据结构；
  - 实现顺序；
  - 最小闭环路径。

---

## 7. 下一步最值得先做的两件事

1. **先实现 1 个最小闭环 case**
   - 例如 `无工具发布任务` 或 `否定式工具约束`。

2. **把证据格式定死**
   - JSONL 记录格式；
   - issue 字段格式；
   - 汇总报告模板。

如果这两件事先定下来，后续扩展会快很多。
