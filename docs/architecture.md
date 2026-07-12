# Alpha-Agent 整体架构

## 一、系统定位

Alpha-Agent 是一个**数据驱动的投资分析智能体**，核心理念：数据驱动、客观分析、风险优先。基于 LangGraph 构建 Agent 循环，支持流式对话、工具调用、子 Agent 委派、流水线执行，并具备自学习与自维护能力。

---

## 二、分层架构总览

```
┌─────────────────────────────────────────────────────┐
│                    接入层 (Access)                    │
│              FastAPI SSE / CLI                       │
├─────────────────────────────────────────────────────┤
│                    核心层 (Core)                      │
│     AgentLoop · LangGraph · Guardrail · Budget      │
│     ContextCompressor · LearningLoop · Curator      │
├─────────────────────────────────────────────────────┤
│                    工具层 (Tools)                     │
│   Core · Market · Analysis · Portfolio · Data · Viz │
├─────────────────────────────────────────────────────┤
│                    领域层 (Domain)                    │
│   Market · Factor · Backtest · Portfolio · Screener │
│   Quant · Monitor · Comparison · Rotation           │
├─────────────────────────────────────────────────────┤
│                    基础设施层 (Infra)                 │
│   LLM · DB · Cache · Session · Memory · Skill      │
│   Catalog · Profile · Schema · Sync · Process       │
└─────────────────────────────────────────────────────┘
```

---

## 三、核心交互流程

### 3.1 主链路

```
用户请求 → API/CLI → AgentLoop → LangGraph 状态图循环 → 工具调用 → SSE 流式响应
                                                          ↓
                                               后台学习循环 (LearningLoop)
```

### 3.2 LangGraph 状态图

Agent 的核心执行逻辑是一个三节点循环图：

```
         ┌──────────────────────────────────────┐
         │                                      │
         ▼                                      │
   ┌──────────┐     ┌──────────┐               │
   │  agent   │────▶│  tools   │───────────────┘
   │  (LLM)   │     │(ToolNode)│
   └──────────┘     └──────────┘
        │
        │ 无工具调用 / 所有工具被熔断
        ▼
      [END]

        │ 步数超限 / 连续12步仅工具调用
        ▼
   ┌──────────┐
   │ finalize │────▶ [END]
   │(总结回答) │
   └──────────┘
```

**节点职责：**

| 节点 | 职责 |
|------|------|
| agent | 调用 LLM，决定下一步动作（调用工具或直接回答） |
| tools | 执行 LLM 选择的工具调用 |
| finalize | 步数超限时，让 LLM 基于已有信息总结最终回答 |

**路由规则 (should_continue)：**

| 条件 | 路由目标 |
|------|----------|
| LLM 返回纯文本（无 tool_calls） | END |
| 步数达到上限 | finalize |
| 所有待调用工具被熔断阻断 | END |
| 连续 12 步仅工具调用无文本输出 | finalize |
| 其他 | tools（继续执行） |

### 3.3 单步执行流程 (agent_node)

每一步 agent_node 内部按以下顺序处理：

1. **迭代预算检查** — 超出则强制结束
2. **LLM 服务可用性检查**
3. **熔断器状态恢复** — 从历史消息重建熔断状态
4. **上下文构建** — 时间前缀 + System Prompt + 对话历史
5. **工具失败检测** — 检测历史中的工具失败并注入提示
6. **熔断警告注入** — 告知 LLM 哪些工具已被阻断
7. **上下文压缩** — 按需压缩过长对话历史
8. **调用 LLM** — bind_tools 后 invoke，决定动作
9. **熔断器记录** — after_call 更新熔断计数

---

## 四、核心机制

### 4.1 熔断机制 (ToolCallGuardrail)

防止同一工具连续失败导致无限重试：

- 同一工具连续失败达到阈值 → 自动阻断该工具
- 同一工具 + 相同参数重复调用 → 阻断
- 阻断后注入提示，告知 LLM 不要再调用
- 所有待调用工具均被阻断 → 提前结束循环

### 4.2 迭代预算 (IterationBudget)

控制 Agent 执行步数，防止死循环：

- 每步 increment，超出 max_iterations 则强制结束
- 预算按会话隔离，不同会话独立计数
- 超限时进入 finalize 节点生成总结回答

### 4.3 上下文压缩 (ContextCompressor)

对话过长时自动压缩历史，避免超出 token 限制：

- **预检** — 估算当前消息 token 数，判断是否需要压缩
- **压缩** — 将历史消息压缩为结构化摘要
- **持久化** — 摘要存入数据库，支持后续检索
- **分类标签** — 摘要包含内容分类，保留关键信息

### 4.4 子 Agent 委派 (delegate_task)

动态创建专业子 Agent 执行特定任务：

- 通过 ProfileLoader 加载不同 Profile
- 每个 Profile 定义：system_prompt、受限工具集、最大迭代步数
- 支持单任务委派和多任务并发派发 (fan-out)
- 默认后台执行，不阻塞主对话

**可用 Profile：**

| Profile | 定位 |
|---------|------|
| fundamental_analyst | 基本面分析（估值、财报、盈利能力） |
| technical_analyst | 技术面分析（走势、指标、支撑阻力） |
| risk_controller | 风险控制（仓位、回撤、VaR） |
| data_engineer | 数据工程（同步、清洗、验证） |
| backtest_engineer | 回测工程（策略回测、绩效评估） |

### 4.5 流水线执行 (execute_pipeline)

预构建的领域工作流，比逐步调用工具更高效：

| 流水线 | 说明 |
|--------|------|
| stock_analysis | 全量股票分析（基本面 + 技术面 + 风险） |
| stock_screening | 股票筛选（池 → 因子 → 排名 → 输出） |
| factor_backtest | 因子回测（选股 → 因子 → 回测 → 绩效） |
| portfolio_build | 组合构建（股票 → 权重 → 压力测试） |
| market_overview | 市场全景（含异常检测） |
| data_health_check | 数据健康检查 |
| data_auto_repair | 数据自动修复 |

### 4.6 渐进式技能加载 (skill_manage)

按需加载扩展工具，减少初始 token 消耗：

- 初始只加载核心工具集
- LLM 可通过 skill_manage 工具动态请求加载扩展工具
- 扩展工具加载后即可在后续步骤中使用

### 4.7 后台学习循环 (LearningLoop)

每次对话后异步执行，实现自学习：

1. **Review** — 评估对话质量，计算 ReviewScore
2. **Learn** — 满足条件时沉淀为 Skill
3. **Store** — 通过 SkillStore 持久化存储
4. **Graph** — LearningGraph 构建 Skill 关系图

### 4.8 自动维护 (Curator)

定期自动维护系统状态：

- 检查 Skill 是否过期 → 自动归档/退役
- 合并重复 Skill
- 清理过期记忆
- 生成整合报告

---

## 五、工具体系

### 5.1 分层加载策略

| 层级 | 加载时机 | 包含工具 |
|------|----------|----------|
| 核心工具 | 始终加载 | terminal、process、execute_code、execute_pipeline、delegate_task、get_database_schema、get_current_time、web_tools、chart_tools、insight_tools、attribution_tools |
| 扩展工具 | skill_manage 按需加载 | 行情、新闻、回测、选股、因子、组合、监控等 |
| 子 Agent 工具 | delegate_task 时按 Profile 加载 | Profile 定义的受限工具子集 |

### 5.2 工具分类

| 分类 | 工具 | 说明 |
|------|------|------|
| **核心** | terminal, process, execute_code | 基础执行能力 |
| **核心** | execute_pipeline, delegate_task | 工作流与委派 |
| **数据** | web_search, web_fetch, get_database_schema | 数据获取 |
| **市场** | 行情查询, 新闻, 公告, 实时报价, 监控告警, 宏观数据 | 市场信息 |
| **分析** | 回测, 选股, 因子, 对比, 归因, 洞察, 知识图谱 | 分析能力 |
| **组合** | 创建/管理组合, 风险分析, 再平衡建议 | 组合管理 |
| **可视化** | chart_tools | 图表生成 |

---

## 六、基础设施

| 组件 | 职责 |
|------|------|
| **LLMService** | LLM 调用封装，支持 chat / chat_with_messages / structured_output |
| **Database** | PostgreSQL，存储会话、审计日志、Skill、记忆等 |
| **SessionStore** | 会话记录，支持搜索与浏览 |
| **SessionLifecycle** | 会话生命周期管理（创建/恢复/分支/压缩续接/归档/删除） |
| **MemoryStore** | 用户记忆管理（添加/搜索/整合/过期清理） |
| **SkillStore** | Skill 存储（创建/编辑/派生/退役/搜索/使用统计） |
| **DataCatalog** | 数据地图，从 PG 元数据自动构建，注入 System Prompt |
| **ProfileLoader** | 子 Agent Profile 加载与缓存 |
| **Cache** | 通用缓存层 |
| **Sync** | 数据同步服务 |

---

## 七、API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| /api/chat/stream | POST | SSE 流式对话（核心端点） |
| /api/conversations | GET | 对话历史列表 |
| /api/conversations/{id} | GET | 对话详情 |
| /api/conversations/{id} | DELETE | 删除对话 |
| /api/tracer/stats | GET | 追踪统计 |
| /api/tracer/traces | GET | 追踪记录 |

---

## 八、SSE 事件协议

| 事件 | 数据 | 说明 |
|------|------|------|
| start | thread_id, mode | 分析开始 |
| tool_call | id, name, args | 工具调用 |
| token | content | LLM 生成文本 |
| tool_result | status | 工具执行结果 |
| done | thread_id, response, tool_calls, duration_ms, steps | 分析完成 |
| error | message | 异常 |
