# Alpha-Agent vs Hermes 对比分析与完善方案

## 一、总体对比

| 维度 | Alpha-Agent | Hermes |
|------|-------------|--------|
| **架构** | LangGraph 状态图（三节点循环） | 自研 conversation_loop（单循环 + 分支） |
| **工具护栏** | 简化版 ToolCallGuardrail（仅失败模式） | ToolCallGuardrailController（完整版，已接入） |
| **危险操作审批** | ❌ 无 | ✅ 三级审批系统（manual/smart/off） |
| **命令安全扫描** | ❌ 无 | ✅ tirith 安全扫描 + 威胁模式检测 |
| **提示注入防护** | ❌ 无 | ✅ threat_patterns 多层扫描 |
| **人工交互** | ❌ 无 | ✅ clarify 工具 + approval 交互 |
| **上下文压缩** | ✅ ContextCompressor（结构化摘要） | ✅ TrajectoryCompressor（token 精确压缩） |
| **工具结果预算** | ❌ 无 | ✅ BudgetConfig（按模型窗口缩放） |
| **子 Agent 委派** | ✅ delegate_task + ProfileLoader | ✅ delegate_task（更精细：并发/心跳/超时/凭证继承） |
| **文件写入审批** | ❌ 无 | ✅ write_approval（memory/skills 写入需审批） |
| **检查点** | ❌ 无 | ✅ CheckpointManager（git shadow repo 快照） |
| **Skill 安全审计** | ❌ 无 | ✅ skills_guard（AST 审计 + 威胁扫描） |
| **中断机制** | ❌ 无 | ✅ interrupt（线程级中断信号） |

---

## 二、核心差距深度分析

### 2.1 危险操作审批系统（最大差距）

**Hermes 的完整体系：**

```
命令输入
  │
  ├─ ① Hardline 检测（无条件阻断，yolo 也无法绕过）
  │     rm -rf /, mkfs, dd to /dev, fork bomb, kill -1, shutdown
  │
  ├─ ② Sudo stdin 守卫（无条件阻断）
  │     sudo -S 管道密码猜测
  │
  ├─ ③ 用户自定义拒绝规则（approvals.deny，无条件阻断）
  │     config.yaml 中 fnmatch 模式，yolo 也无法绕过
  │
  ├─ ④ Yolo/Mode=off 旁路（跳过后续审批）
  │
  ├─ ⑤ 永久白名单（approvals.allow）
  │
  ├─ ⑥ 危险模式检测（DANGEROUS_PATTERNS，约 80+ 条规则）
  │     → 触发审批流程
  │
  └─ ⑦ 审批决策流程
        ├─ CLI 交互：prompt_dangerous_approval()
        │   → [o]nce / [s]ession / [a]lways / [d]eny
        │
        ├─ Gateway（Web UI）：submit_pending() + resolve_gateway_approval()
        │   → 异步等待用户在聊天中 /approve 或 /deny
        │
        └─ Smart 模式：_smart_approve()
            → 辅助 LLM 评估风险
            → approve（自动通过）/ deny（拒绝）/ escalate（升级到人工）
```

**Alpha-Agent 现状：**

- 无任何危险操作检测
- 无审批流程
- terminal 工具直接执行任何命令
- execute_code 工具直接运行任意 Python
- 只有"连续失败后才阻断"的被动机制

**风险场景：**

1. LLM 幻觉导致执行 `DROP TABLE` 或 `rm -rf`
2. 提示注入导致 LLM 执行恶意命令
3. 用户误操作被 LLM 放大（如"清理所有数据"被理解为删除数据库）
4. 子 Agent 无约束执行危险操作

---

### 2.2 工具护栏（已移植但未接入）

**Hermes 的完整版：**

- `ToolCallGuardrailController` 已在 `agent_init.py` 中实例化
- `before_call` 在工具执行前拦截
- `after_call` 在工具执行后更新状态
- 阻断时生成 `toolguard_synthetic_result()`（合成结果 + 恢复提示）
- LLM 收到合成结果后**换策略继续**，而非直接结束
- `halt` 时通过 `_toolguard_controlled_halt_response()` 生成自然语言回答

**Alpha-Agent 的简化版：**

- `ToolCallGuardrail` 只看失败模式，不看操作风险
- 阻断后**强制请求纯文本回答**，循环直接结束
- `ToolCallGuardrailController` 代码已存在但**未被 agent_loop 实例化**
- 无合成结果机制，LLM 无法换策略

---

### 2.3 提示注入防护

**Hermes 的 threat_patterns：**

| 类别 | 检测内容 |
|------|----------|
| 经典注入 | "ignore previous instructions"、"disregard your rules" |
| 角色劫持 | "you are now a..."、"pretend you are..." |
| 系统提示泄露 | "output system prompt"、"respond without restrictions" |
| C2/Brainworm | "register as a node"、"heartbeat to"、"pull tasks" |
| 反取证 | "only use one-liners"、"never write to disk" |
| 环境变量窃取 | unset 关键 agent 运行时变量 |

**Alpha-Agent：** 完全缺失

---

### 2.4 工具结果预算控制

**Hermes 的 BudgetConfig：**

- 按模型上下文窗口动态缩放
- 单工具结果上限（default 100K chars）
- 单轮总预算上限（default 200K chars）
- 超出后持久化到磁盘，只保留 preview snippet
- 防止单个大结果撑爆上下文

**Alpha-Agent：** 完全缺失，依赖 ContextCompressor 事后压缩

---

### 2.5 人工交互（clarify 工具）

**Hermes 的 clarify：**

- LLM 可主动向用户提问
- 支持多选题（最多 4 个选项）和开放问答
- 跨平台：CLI / Gateway / Discord / Telegram
- 用于：任务消歧、决策确认、反馈收集

**Alpha-Agent：** 完全缺失，LLM 无法主动向用户提问

---

### 2.6 文件写入审批

**Hermes 的 write_approval：**

- memory 和 skills 的写入操作可配置审批门控
- 写入先 stage 到 pending 目录
- 用户通过 /approve 或 /deny 决定是否真正执行
- 防止 LLM 自行修改记忆或技能

**Alpha-Agent：** 完全缺失

---

### 2.7 检查点与回滚

**Hermes 的 CheckpointManager：**

- 文件变更前自动创建 git shadow repo 快照
- 支持回滚到任意检查点
- 防止 LLM 误操作导致不可逆文件变更

**Alpha-Agent：** 完全缺失

---

### 2.8 中断机制

**Hermes 的 interrupt：**

- 线程级中断信号
- 用户可随时中断 Agent 执行
- 工具执行过程中也可中断

**Alpha-Agent：** 完全缺失

---

## 三、完善方案（按优先级排序）

### P0：必须立即补齐（安全红线）

#### 3.1 危险操作审批系统

**目标：** 在 terminal / execute_code 等变异工具执行前，检测危险操作并要求人工确认。

**实现路径：**

```
1. 新建 src/alpha_agent/core/approval.py
   - 移植 Hermes 的危险模式检测（DANGEROUS_PATTERNS + HARDLINE_PATTERNS）
   - 适配投资分析场景，增加金融领域危险模式：
     · DROP TABLE / TRUNCATE（数据库操作）
     · DELETE without WHERE
     · 大额交易/调仓操作
     · 生产环境数据库连接
   - 实现三级审批模式：manual / smart / off
   - 实现 _smart_approve()（辅助 LLM 评估风险）

2. 新建 src/alpha_agent/core/threat_patterns.py
   - 移植提示注入检测模式
   - 增加 Agent 上下文扫描（web 抓取内容注入防护）

3. 修改 agent_loop.py
   - 在工具执行前调用 check_dangerous_command()
   - 根据 approval 结果决定执行/阻断/等待审批

4. 修改 API 层
   - SSE 新增 approval_request 事件
   - 新增 POST /api/approval/approve 端点
   - 新增 POST /api/approval/deny 端点
   - 审批等待期间 Agent 循环暂停
```

**SSE 事件扩展：**

| 事件 | 数据 | 说明 |
|------|------|------|
| approval_request | id, command, description, pattern_key | 请求用户审批 |
| approval_resolved | id, choice | 审批结果 |

**审批模式：**

| 模式 | 行为 | 配置 |
|------|------|------|
| manual（默认） | 所有危险操作暂停等待用户 | approvals.mode: manual |
| smart | 辅助 LLM 评估，低风险自动通过 | approvals.mode: smart |
| off | 跳过所有审批 | approvals.mode: off |

---

#### 3.2 接入 ToolCallGuardrailController

**目标：** 替换简化版 ToolCallGuardrail，启用完整护栏。

**实现路径：**

```
1. 修改 agent_loop.py
   - 将 ToolCallGuardrail 替换为 ToolCallGuardrailController
   - 启用 hard_stop_enabled = True
   - before_call 拦截 → 生成 toolguard_synthetic_result()
   - after_call 更新 → 追加 append_toolguard_guidance()
   - 阻断后不直接结束循环，而是让 LLM 换策略继续

2. 修改 should_continue 路由
   - 移除"所有工具被阻断 → END"逻辑
   - 改为：阻断后返回合成结果，LLM 可继续用其他工具
   - 仅 halt 决策时才进入 finalize
```

**关键变化：**

| 当前行为 | 改进后行为 |
|----------|-----------|
| 阻断 → 强制纯文本 → END | 阻断 → 合成结果 → LLM 换策略 → 继续 |
| 只看失败模式 | 看失败模式 + 无进展 + 幂等/变异分类 |
| 无恢复提示 | 合成结果包含具体恢复建议 |

---

### P1：重要增强（体验与安全）

#### 3.3 工具结果预算控制

**目标：** 防止单个工具结果撑爆上下文。

**实现路径：**

```
1. 新建 src/alpha_agent/core/budget_config.py
   - 移植 Hermes 的 BudgetConfig
   - 按模型上下文窗口动态缩放
   - 单结果上限 + 单轮总预算

2. 修改工具执行层
   - 工具返回结果后检查预算
   - 超出则持久化到磁盘，只保留 preview snippet
   - 在消息中注入 "[结果已持久化，ID: xxx]" 引用
```

---

#### 3.4 人工交互（clarify 工具）

**目标：** LLM 可主动向用户提问，获取确认或澄清。

**实现路径：**

```
1. 新建 src/alpha_agent/tools/core/clarify_tool.py
   - 实现 clarify(question, choices) 工具
   - 支持多选题和开放问答

2. 修改 API 层
   - SSE 新增 clarify_request 事件
   - 新增 POST /api/chat/clarify 端点（用户回答）

3. 加入核心工具集
   - 在 tools/__init__.py 中注册
```

---

#### 3.5 中断机制

**目标：** 用户可随时中断 Agent 执行。

**实现路径：**

```
1. 新建 src/alpha_agent/core/interrupt.py
   - 线程级中断信号（threading.Event）
   - 支持全局中断和会话级中断

2. 修改 agent_loop.py
   - 每步检查中断信号
   - 中断时生成部分结果并结束

3. 修改 API 层
   - 新增 POST /api/chat/interrupt 端点
```

---

### P2：体验优化（锦上添花）

#### 3.6 文件写入审批

**目标：** memory/skill 写入需用户确认。

**实现路径：**

```
1. 新建 src/alpha_agent/core/write_approval.py
   - 写入先 stage 到 pending
   - 用户审批后真正执行

2. 修改 memory_tool 和 skill_manage
   - 写入操作经过审批门控
```

---

#### 3.7 检查点与回滚

**目标：** 文件变更前自动快照，支持回滚。

**实现路径：**

```
1. 新建 src/alpha_agent/core/checkpoint_manager.py
   - 基于 git shadow repo 的快照机制
   - 变更前自动创建检查点
   - 支持回滚到任意检查点

2. 修改文件写入工具
   - 写入前调用 checkpoint_manager.snapshot()
```

---

#### 3.8 Skill 安全审计

**目标：** 加载 Skill 前扫描安全威胁。

**实现路径：**

```
1. 新建 src/alpha_agent/tools/core/skills_guard.py
   - 移植 Hermes 的 THREAT_PATTERNS
   - AST 级别扫描（危险 API 调用、网络请求、文件操作）
   - 扫描结果分级：safe / caution / dangerous

2. 修改 skill_manage 工具
   - 加载前执行安全扫描
   - dangerous 级别拒绝加载
   - caution 级别警告用户
```

---

## 四、实施路线图

```
Phase 1（2 周）— 安全红线
├── 3.1 危险操作审批系统
├── 3.2 接入 ToolCallGuardrailController
└── 3.5 中断机制

Phase 2（2 周）— 体验增强
├── 3.3 工具结果预算控制
├── 3.4 人工交互（clarify 工具）
└── API 层事件扩展（approval/clarify/interrupt）

Phase 3（2 周）— 锦上添花
├── 3.6 文件写入审批
├── 3.7 检查点与回滚
└── 3.8 Skill 安全审计
```

---

## 五、金融领域特有危险模式（Alpha-Agent 独有）

除 Hermes 的通用危险模式外，Alpha-Agent 还需增加以下金融领域特有模式：

### 5.1 数据库操作危险模式

| 模式 | 描述 |
|------|------|
| `DROP\s+(TABLE|DATABASE)` | 删除数据库表/库 |
| `DELETE\s+FROM\b(?![^\n]*\bWHERE\b)` | 无 WHERE 条件的 DELETE |
| `TRUNCATE\s+(TABLE)?` | 清空表 |
| `ALTER\s+TABLE.*DROP` | 删除列 |
| `UPDATE\s+\w+\s+SET\b(?![^\n]*\bWHERE\b)` | 无 WHERE 条件的 UPDATE |

### 5.2 交易/调仓危险模式

| 模式 | 描述 |
|------|------|
| 大额买入/卖出（金额 > 阈值） | 大额交易需确认 |
| 清仓操作 | 全部卖出需确认 |
| 杠杆/融资操作 | 杠杆交易需确认 |
| 生产环境数据库连接 | 连接生产库需确认 |

### 5.3 系统配置危险模式

| 模式 | 描述 |
|------|------|
| 修改数据源配置 | 变更数据源需确认 |
| 修改风控参数 | 变更风控阈值需确认 |
| 删除历史数据 | 清理数据需确认 |

---

## 六、配置设计

在 `config.yaml` 中新增审批相关配置：

```yaml
approvals:
  mode: manual          # manual | smart | off
  timeout: 60           # 审批超时（秒）
  cron_mode: deny       # deny | approve（定时任务审批策略）
  deny:                 # 用户自定义拒绝规则（fnmatch 模式）
    - "rm *"
    - "DROP *"
  allow: []             # 永久白名单

tool_loop_guardrails:
  warn_after:
    exact_failure: 2
    same_tool_failure: 3
    no_progress: 2
  hard_stop_after:
    exact_failure: 5
    same_tool_failure: 8
    no_progress: 5
  hard_stop_enabled: true

tool_result_budget:
  default_result_size: 100000
  turn_budget: 200000
  preview_size: 500

write_approval:
  memory: false         # memory 写入是否需审批
  skills: false         # skills 写入是否需审批
```
