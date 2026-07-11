# 投资分析 Agent 重构计划与验收文档

> 借鉴 Hermes 核心能力，专注投资分析领域，释放 PostgreSQL 全部能力
>
> 创建日期：2026-07-11

---

## 一、定位与原则

### 1.1 定位

Hermes 是通用 Agent 的天花板，我们要做投资分析 Agent 的天花板。

通用 Agent 靠广度取胜，专业 Agent 靠深度取胜。Hermes 的核心能力（terminal/process/execute_code/delegate_task/skill_manage/Closed Learning Loop）我们全部继承，同时用领域专注 + PG 能力构建它做不到的深度。

### 1.2 设计原则

| 原则 | 含义 |
|------|------|
| **不迁就现有架构** | 废弃该废弃的，重建该重建的，不被历史包袱拖累 |
| **继承 Hermes 核心能力** | terminal/process/execute_code/delegate_task/skill_manage/Closed Learning Loop 全部继承 |
| **专业深化** | 预建投资领域知识、Pipeline、Skill，Agent 启动即懂业务 |
| **释放 PG 能力** | 物化视图、pg_cron、LISTEN/NOTIFY、JSONB、全文搜索——不再把 PG 当 SQLite 用 |
| **以目标为导向** | 用户说"同步数据"就不用管，Agent 自主完成闭环 |

---

## 二、现状问题

### 2.1 架构哲学错误——人在替 Agent 做决策

当前流程：用户输入 → 关键词匹配 → 选 Worker → 固定工具 → 固定 prompt → 执行

本质是人预设了"什么问题该谁答"，但真实场景远比关键词复杂。

### 2.2 工具膨胀失控——40+ 工具全部注入 LLM 上下文

LLM 面对 40 个选项时选择准确率骤降，且 token 浪费严重。

### 2.3 执行模型阻塞——Agent 在等结果时完全卡死

选股扫描 5800 只股票需要 3 小时，期间 Agent 完全无响应。

### 2.4 无经验积累——每次执行都是第一次

Agent 第 100 次同步数据和第 1 次一样笨。

### 2.5 PG 能力严重浪费——当 SQLite 用

15 张表有 JSON 字段但从未用过 JSONB 查询。没有物化视图。没有 pg_cron。没有 LISTEN/NOTIFY。

### 2.6 分析能力碎片化——6 个 Service 各自为战，无法组合

FactorService、StockScreener、IndustryRotation、StockComparison、FactorBacktestEngine、PortfolioService 各自独立，但真实分析需要组合。

### 2.7 数据维护无闭环——靠人发现、靠人修复

Agent 不知道数据是否落后，同步失败不会重试。

---

## 三、改造总览

### 3.1 七大改造域

| # | 改造域 | 借鉴 Hermes | 我们的专业深化 |
|---|--------|------------|--------------|
| 1 | Agent 核心 | 单 Agent 持久循环 + delegate_task | 预置投资分析领域知识，Agent 启动即懂业务 |
| 2 | 执行引擎 | terminal + process + execute_code | 数据操作脚本化，投资分析 Pipeline 化 |
| 3 | 工具体系 | 精简核心工具集 + 按需加载 | 投资分析 Pipeline 替代碎片工具组合 |
| 4 | 技能系统 | skill_manage + Closed Learning Loop | PG 驱动 Skill 存储 + 投资领域预置 Skill |
| 5 | 记忆系统 | 三层记忆（Frozen + Episodic + Skill） | PG 驱动记忆 + 投资领域结构化记忆 |
| 6 | 数据层 | terminal 执行脚本 | PG 物化视图 + pg_cron + LISTEN/NOTIFY |
| 7 | 交互层 | 后台任务 + 进度查询 | PG 事件驱动 + 实时推送 |

### 3.2 改造前后全景对比

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| **架构** | Supervisor + 6 固定 Worker + 关键词路由 | AgentLoop + delegate_task + Profile |
| **执行** | execute_python 同步阻塞 | terminal 前台/后台 + process 管理 |
| **工作流** | LLM 多轮调用，中间结果污染上下文 | execute_pipeline 一步到位 + execute_code 压缩 |
| **分析** | 6 个独立 Service，无法组合 | Pipeline 编排框架，可组合可复用 |
| **工具** | 40+ 全部注入 LLM | 15 核心 + Pipeline + PG 原生 |
| **记忆** | JSON 文件，4 字段 | PG 驱动三层记忆 + 全文搜索 |
| **技能** | 人写 Markdown，关键词匹配 | Agent 自建 Skill + 闭环学习 + PG 全文搜索 |
| **数据** | APScheduler + 手动检查 | pg_cron + 物化视图 + LISTEN/NOTIFY |
| **进度** | 无感知 | process(poll) + PG NOTIFY 事件推送 |
| **数据库** | PG 当 SQLite 用 | PG 全部能力：JSONB、窗口函数、物化视图、pg_cron、LISTEN/NOTIFY、全文搜索 |
| **经验** | 无积累 | Closed Learning Loop，越用越聪明 |

---

## 四、阶段一：换发动机（2 周）✅ 已完成

### 4.1 目标

Agent 能后台执行、查进度、跑 Pipeline——从"卡死等结果"到"并行不阻塞"

### 4.2 改造内容

| # | 改造项 | 说明 | 产出文件 |
|---|--------|------|---------|
| 1 | ProcessRegistry | 子进程生命周期管理（启动/查询/终止/超时 kill） | services/process_registry.py |
| 2 | terminal 工具 | 前台/后台执行任意命令 | tools/terminal.py |
| 3 | process 工具 | poll/wait/list/kill/log 管理后台进程 | tools/process.py |
| 4 | execute_code 工具 | 多步工作流压缩为一次调用，中间结果不进上下文 | tools/execute_code.py |
| 5 | 数据操作脚本化 | 将 DataSyncService 的每个同步方法拆为独立脚本 | scripts/sync_stock_list.py, sync_stock_kline.py, sync_financial_data.py, sync_etf_data.py, sync_money_flow.py, sync_industry_agg.py, sync_macro_data.py, calc_stock_factors.py, sync_all_data.py |
| 6 | Pipeline 框架 | 可组合的分析步骤编排 | services/pipeline/base.py |
| 7 | stock_analysis Pipeline | 基本面→技术面→风控→综合评级→报告 | services/pipeline/stock_analysis.py |
| 8 | market_overview Pipeline | 行情统计→行业涨跌→资金流向→异常检测→报告 | services/pipeline/market_overview.py |
| 9 | data_health_check Pipeline | 全表扫描→缺失检测→新鲜度评估→修复建议 | services/pipeline/data_health_check.py |
| 10 | execute_pipeline 工具 | 一步执行预置分析工作流 | tools/pipeline.py |
| 11 | AgentLoop | 单 Agent 持久循环 + 核心工具集（15 个），AgentGraphBuilder 负责图构建 | core/agent_loop.py |
| 12 | 后台执行公共工具 | 统一临时脚本写入 + 后台启动 + 消息格式化 | utils/executor.py |

### 4.3 废弃

- tools/code_executor.py 的 execute_python 工具（被 execute_code 替代，文件保留用于其他工具引用，代码删除延迟到阶段四）
- services/scheduler/service.py 的 APScheduler（被 terminal + background 替代，文件保留用于兼容，代码删除延迟到阶段四）

### 4.4 验收标准

| # | 验收场景 | 期望结果 |
|---|---------|---------|
| V1-1 | 用户说"同步 K 线数据" | Agent 后台执行，立即返回 task_id，不阻塞 |
| V1-2 | 用户问"同步到哪了" | Agent 回答进度百分比和预计剩余时间 |
| V1-3 | 同步期间用户问其他问题 | Agent 正常回答，不受同步任务影响 |
| V1-4 | 用户说"分析平安银行" | Agent 执行 stock_analysis Pipeline，一步输出完整报告 |
| V1-5 | 用户说"市场今天怎么样" | Agent 执行 market_overview Pipeline，直接出市场概览 |
| V1-6 | 用户说"检查数据健康" | Agent 执行 data_health_check Pipeline，输出各表健康状态 |
| V1-7 | 后台同步出错 | Agent 可通过 process(kill) 终止，而非等 3 小时 |
| V1-8 | terminal 执行 Shell 命令 | 如 `terminal("pip list")` 正常返回结果 |

### 4.5 验收结果

> 验收日期：2026-07-11
> 验收方式：手动场景验证 + AgentLoop 图构建验证 + Pipeline 注册验证
> 结果：10/10 项全部通过 ✅

| # | 验收场景 | 结果 |
|---|---------|------|
| V1-1 | 后台同步 K 线数据 | ✅ 通过 - 后台执行立即返回 task_id |
| V1-2 | 查询同步进度 | ✅ 通过 - process(poll) 返回进度和输出 |
| V1-3 | 同步期间并发查询 | ✅ 通过 - 后台任务不影响前台查询 |
| V1-4 | stock_analysis Pipeline | ✅ 通过 - 平安银行分析报告完整输出 |
| V1-5 | market_overview Pipeline | ✅ 通过 - 市场概览含行情/行业/异常 |
| V1-6 | data_health_check Pipeline | ✅ 通过 - 各表健康状态和修复建议 |
| V1-7 | 终止后台任务 | ✅ 通过 - process(kill) 可终止长时间任务 |
| V1-8 | terminal 执行命令 | ✅ 通过 - 前台执行返回完整输出 |
| 额外 | AgentLoop 图构建 | ✅ 通过 - 18个核心工具加载 |
| 额外 | Pipeline 注册 | ✅ 通过 - 3个 Pipeline 注册成功 |

---

## 五、阶段二：让 Agent 越用越聪明（2 周）

### 5.1 目标

经验自动沉淀、技能自动进化、专业 Profile 按需加载

### 5.2 改造内容

| # | 改造项 | 说明 | 产出文件 |
|---|--------|------|---------|
| 1 | PG agent_skills 表 | 结构化 Skill 存储，JSONB 索引 + 全文搜索 | storage/migrations/004_agent_skills.sql |
| 2 | PG agent_memory 表 | 三层记忆（Frozen/Episodic/SkillRef），JSONB + 标签 + 访问统计 | storage/migrations/005_agent_memory.sql |
| 3 | skill_manage 工具 | create/update/fork/retire/list/search | tools/skill_manage.py |
| 4 | Skill Store 服务 | PG 驱动的 Skill 持久化与检索 | services/skill_store.py |
| 5 | Closed Learning Loop | 每轮对话后后台 fork 重放，评分规则判断是否沉淀 Skill | core/learning_loop.py |
| 6 | delegate_task 工具 | 动态创建子 Agent，加载 Profile，支持后台模式 | tools/delegate.py |
| 7 | Profile 系统 | 将现有 Worker 的 prompt+工具配置转为 YAML Profile | profiles/fundamental_analyst.yaml, technical_analyst.yaml, risk_controller.yaml, data_engineer.yaml, backtest_engineer.yaml |
| 8 | stock_screening Pipeline | 获取标的池→因子计算→排名筛选→输出 | services/pipeline/stock_screening.py |
| 9 | factor_backtest Pipeline | 选股→因子构建→回测→绩效评估 | services/pipeline/factor_backtest.py |
| 10 | portfolio_build Pipeline | 选股→权重优化→风控检查→组合构建 | services/pipeline/portfolio_build.py |
| 11 | data_auto_repair Pipeline | 诊断→重试/切换源→补数据→验证→沉淀 Skill | services/pipeline/data_auto_repair.py |
| 12 | 预置投资领域 Skill | 12 个核心 Skill（数据同步、健康检查、个股分析、选股、回测等） | scripts/seed_preset_skills.py |
| 13 | Memory Store 服务 | PG 驱动的三层记忆读写 | services/memory_store.py |

> 验收日期：2026-07-11
> 验收方式：自动化验证（语法检查 + 数据库建表 + 预设技能创建 + Pipeline 注册 + Learning Loop 评分 + 工具集加载）
> 结果：13/13 项全部通过 ✅

### 5.3 废弃

- tools/memory_tools.py（JSON 文件记忆）
- skills/markdown_skill.py（Markdown Skill + 关键词匹配）
- skills/base.py（关键词匹配逻辑）
- agents/supervisor.py（Supervisor 路由）
- agents/manager.py（关键词路由）
- graph/multi_agent_graph.py（固定流水线）

### 5.4 验收标准

| # | 验收场景 | 期望结果 |
|---|---------|---------|
| V2-1 | 首次同步 ETF 数据 | 执行完成后自动生成 Skill |
| V2-2 | 第二次同步 ETF 数据 | Agent 搜索到已有 Skill，直接复用，执行更快 |
| V2-3 | 数据源 API 变更导致 Skill 失败 | Agent 自动修正 Skill（improve_skill） |
| V2-4 | delegate_task(profile="fundamental_analyst") | 创建专业子 Agent，使用基本面分析 prompt 和工具 |
| V2-5 | delegate_task(background=True) | 子 Agent 后台执行，主 Agent 继续工作 |
| V2-6 | Agent 启动 | 自动查询数据健康状态，注入 system prompt |
| V2-7 | 数据同步失败 | Agent 自主诊断原因、重试或切换数据源 |
| V2-8 | skill_manage(search, "选股") | 返回匹配的选股相关 Skill 列表 |
| V2-9 | 执行 stock_screening Pipeline | 全市场扫描→因子排名→筛选→输出，一步完成 |
| V2-10 | 执行 factor_backtest Pipeline | 因子策略回测一步完成，输出绩效报告 |

---

## 六、阶段三：释放 PG 全部能力（2 周）

### 6.1 目标

PG 不再当 SQLite 用，物化视图加速查询、pg_cron 替代 Python 调度、事件驱动替代轮询

### 6.2 改造内容

| # | 改造项 | 说明 | 产出文件 |
|---|--------|------|---------|
| 1 | 物化视图 mv_data_health | 各表记录数、最新日期、健康状态 | storage/migrations/002_materialized_views.sql |
| 2 | 物化视图 mv_industry_latest | 行业最新聚合（替代实时计算） | 同上 |
| 3 | 物化视图 mv_stock_factor_latest | 最新因子排名 | 同上 |
| 4 | 物化视图 mv_market_overview | 市场概览 | 同上 |
| 5 | pg_cron 定时任务 | 替代 APScheduler，数据同步由 PG 调度 | storage/migrations/003_pg_cron_jobs.sql |
| 6 | LISTEN/NOTIFY | 后台任务完成→PG NOTIFY→Agent 收到事件→自动处理 | services/event_bus.py |
| 7 | EventBus 服务 | 统一事件总线，管理任务完成、数据更新、告警触发 | services/event_bus.py |
| 8 | JSONB 深度利用 | 分析结果、Skill 步骤、记忆内容全部 JSONB 存储+索引查询 | 改造相关 Service |
| 9 | 全文搜索 | pg_trgm 支持 Skill 搜索、记忆搜索 | storage/migrations/006_pg_trgm.sql |
| 10 | API 层 SSE 增强 | 推送后台任务事件、数据更新通知 | 改造 api/main.py |
| 11 | CLI 增强 | 后台任务状态栏、进度条 | 改造 cli.py |

### 6.3 废弃

- services/scheduler/service.py（APScheduler，阶段一已废弃脚本，此阶段删除代码）
- JSON 文件存储（记忆、配置等）

### 6.4 验收标准

| # | 验收场景 | 期望结果 |
|---|---------|---------|
| V3-1 | Agent 查询数据健康 | 一条 SQL 查 mv_data_health，无需写 Python 脚本 |
| V3-2 | 行业聚合查询 | 查物化视图，速度比实时计算提升 100 倍 |
| V3-3 | 因子排名查询 | 查物化视图，毫秒级返回 |
| V3-4 | 后台同步完成 | PG NOTIFY → Agent 自动收到通知 → 自动检查 → 自动报告用户 |
| V3-5 | 定时数据同步 | pg_cron 按计划执行，无需 Python 进程常驻 |
| V3-6 | Skill 全文搜索 | `skill_manage(search, "股票分析")` 返回语义匹配结果 |
| V3-7 | 记忆全文搜索 | `remember(search, "上次同步")` 返回相关记忆 |
| V3-8 | SSE 事件推送 | 前端实时收到后台任务进度、数据更新通知 |
| V3-9 | 物化视图刷新 | 数据同步完成后自动刷新相关物化视图 |

---

## 七、阶段四：清理整合（1 周）

### 7.1 目标

精简代码、废弃旧系统、全场景回归验证

### 7.2 改造内容

| # | 改造项 | 说明 |
|---|--------|------|
| 1 | 工具分层加载 | 15 核心工具始终加载 + 扩展工具按需加载 |
| 2 | 清理废弃代码 | 删除 code_executor.py、handoff_tools.py、time_tools.py、scheduler/、supervisor.py 路由、manager.py 路由、multi_agent_graph.py |
| 3 | Profile 迁移 | 将现有 Worker 的 prompt + 工具配置转为 YAML Profile |
| 4 | 全场景回归验证 | 今日行情、个股分析、选股、回测、组合构建、数据维护 |

### 7.3 验收标准

| # | 验收场景 | 期望结果 |
|---|---------|---------|
| V4-1 | LLM 上下文 token | 核心工具集 token 比改造前减少 50%+ |
| V4-2 | 今日行情 | Agent 执行 market_overview Pipeline，输出完整报告 |
| V4-3 | 个股分析 | Agent 执行 stock_analysis Pipeline，输出综合评级 |
| V4-4 | 选股 | Agent 执行 stock_screening Pipeline，输出筛选结果 |
| V4-5 | 回测 | Agent 执行 factor_backtest Pipeline，输出绩效报告 |
| V4-6 | 组合构建 | Agent 执行 portfolio_build Pipeline，输出组合配置 |
| V4-7 | 数据维护 | Agent 自主检查→诊断→修复→沉淀 Skill，全程无需人工 |
| V4-8 | 旧入口兼容 | 原有 API 接口仍可用，底层走新架构 |
| V4-9 | 代码量 | 废弃代码删除后，总代码量减少 20%+ |

---

## 八、优先级与依赖关系

```
阶段一（换发动机）
  │
  ├── ProcessRegistry ──→ terminal ──→ process
  │                                ──→ execute_code
  │
  ├── Pipeline 框架 ──→ stock_analysis Pipeline
  │                  ──→ market_overview Pipeline
  │                  ──→ data_health_check Pipeline
  │                  ──→ execute_pipeline 工具
  │
  └── AgentLoop ──→ 集成上述所有工具
  │
  ▼
阶段二（越用越聪明）
  │
  ├── PG agent_skills ──→ skill_manage ──→ Closed Learning Loop
  │
  ├── PG agent_memory ──→ Memory Store ──→ remember 升级
  │
  ├── delegate_task ──→ Profile 系统
  │
  └── 剩余 Pipeline（screening、backtest、portfolio、auto_repair）
  │
  ▼
阶段三（释放 PG 能力）
  │
  ├── 物化视图 ──→ 查询加速
  ├── pg_cron ──→ 定时调度
  ├── LISTEN/NOTIFY ──→ EventBus ──→ SSE 推送
  └── JSONB + 全文搜索 ──→ Skill/记忆搜索
  │
  ▼
阶段四（清理整合）
  │
  ├── 工具分层加载
  ├── 废弃代码清理
  ├── Profile 迁移
  └── 全场景回归
```

---

## 九、风险与应对

| 风险 | 应对措施 |
|------|---------|
| terminal 命令安全 | 白名单机制 + 危险命令确认 + 沙箱 workdir |
| 单 Agent 上下文过长 | execute_code 压缩中间结果 + Skill 减少探索步数 |
| delegate_task 无限递归 | 硬限制 2 层 + 子 Agent 不可再 delegate |
| Learning Loop 产生低质 Skill | 评分规则过滤 + 人工审核开关 + Skill 可 retire |
| 物化视图数据延迟 | 同步完成后自动 REFRESH MATERIALIZED VIEW |
| 旧系统迁移断裂 | 兼容层保留 + 渐进式迁移 + 双跑验证 |
| pg_cron 权限问题 | 使用 pg_cron 扩展需 superuser 权限，部署时需配置 |
| Windows 兼容性 | terminal 在 Windows 下使用 PowerShell，需适配命令语法 |

---

## 十、验收总表

### 阶段一验收（8 项）

- [ ] V1-1 后台同步不阻塞
- [ ] V1-2 进度可查询
- [ ] V1-3 同步期间可回答其他问题
- [ ] V1-4 stock_analysis Pipeline 一步到位
- [ ] V1-5 market_overview Pipeline 直接出报告
- [ ] V1-6 data_health_check Pipeline 输出健康状态
- [ ] V1-7 后台任务可终止
- [ ] V1-8 terminal 执行 Shell 命令

### 阶段二验收（10 项）

- [ ] V2-1 首次执行后自动生成 Skill
- [ ] V2-2 第二次执行复用 Skill
- [ ] V2-3 Skill 失败后自动修正
- [ ] V2-4 delegate_task 加载 Profile
- [ ] V2-5 delegate_task 后台模式
- [ ] V2-6 Agent 启动自动感知数据状态
- [ ] V2-7 数据同步失败自主修复
- [ ] V2-8 Skill 全文搜索
- [ ] V2-9 stock_screening Pipeline
- [ ] V2-10 factor_backtest Pipeline

### 阶段三验收（9 项）

- [ ] V3-1 mv_data_health 一条 SQL 查询
- [ ] V3-2 行业聚合查询速度提升 100 倍
- [ ] V3-3 因子排名毫秒级返回
- [ ] V3-4 后台任务完成自动通知
- [ ] V3-5 pg_cron 定时同步
- [ ] V3-6 Skill 全文搜索
- [ ] V3-7 记忆全文搜索
- [ ] V3-8 SSE 事件推送
- [ ] V3-9 物化视图自动刷新

### 阶段四验收（9 项）

- [ ] V4-1 LLM 上下文 token 减少 50%+
- [ ] V4-2 今日行情场景
- [ ] V4-3 个股分析场景
- [ ] V4-4 选股场景
- [ ] V4-5 回测场景
- [ ] V4-6 组合构建场景
- [ ] V4-7 数据维护自主闭环
- [ ] V4-8 旧入口兼容
- [ ] V4-9 代码量减少 20%+

---

## 附录 A：核心工具集（15 个）

| # | 工具 | 职责 | 来源 |
|---|------|------|------|
| 1 | terminal | 执行任意命令（前台/后台） | 借鉴 Hermes |
| 2 | process | 管理后台进程 | 借鉴 Hermes |
| 3 | execute_code | 多步工作流压缩 | 借鉴 Hermes |
| 4 | delegate_task | 动态子 Agent 委派 | 借鉴 Hermes |
| 5 | skill_manage | 技能全生命周期管理 | 借鉴 Hermes |
| 6 | query_data | 自然语言查询（Text2SQL） | 保留现有 |
| 7 | execute_pipeline | 执行预置分析 Pipeline | 新建（专业深化） |
| 8 | web_search | 搜索外部信息 | 保留现有 |
| 9 | remember | 三层记忆读写 | 升级现有 |
| 10 | get_database_schema | 查看表结构 | 保留现有 |
| 11 | generate_chart | 图表可视化 | 保留现有 |
| 12 | detect_anomalies | 自动洞察 | 保留现有 |
| 13 | attribute_analysis | 归因分析 | 合并现有 |
| 14 | manage_alerts | 告警管理 | 合并现有 |
| 15 | get_current_time | 当前时间 | 保留现有 |

## 附录 B：Pipeline 清单

| # | Pipeline | 工作流 | 阶段 |
|---|----------|--------|------|
| 1 | stock_analysis | 基本面→技术面→风控→综合评级→报告 | 一 |
| 2 | market_overview | 行情统计→行业涨跌→资金流向→异常检测→报告 | 一 |
| 3 | data_health_check | 全表扫描→缺失检测→新鲜度评估→修复建议 | 一 |
| 4 | stock_screening | 获取标的池→因子计算→排名筛选→输出 | 二 |
| 5 | factor_backtest | 选股→因子构建→回测→绩效评估 | 二 |
| 6 | portfolio_build | 选股→权重优化→风控检查→组合构建 | 二 |
| 7 | data_auto_repair | 诊断→重试/切换源→补数据→验证→沉淀 Skill | 二 |

## 附录 C：Profile 清单

| # | Profile | 原对应 Worker | 专业领域 |
|---|---------|-------------|---------|
| 1 | fundamental_analyst | FundamentalWorker | 基本面分析 |
| 2 | technical_analyst | TechnicalWorker | 技术面分析 |
| 3 | risk_controller | 无（新建） | 风险控制 |
| 4 | data_engineer | DataBrain | 数据工程 |
| 5 | backtest_engineer | 无（新建） | 量化回测 |

## 附录 D：PG 新增对象

| # | 对象 | 类型 | 阶段 |
|---|------|------|------|
| 1 | mv_data_health | 物化视图 | 三 |
| 2 | mv_industry_latest | 物化视图 | 三 |
| 3 | mv_stock_factor_latest | 物化视图 | 三 |
| 4 | mv_market_overview | 物化视图 | 三 |
| 5 | agent_skills | 表 | 二 |
| 6 | agent_memory | 表 | 二 |
| 7 | pg_cron 定时任务 | 扩展 | 三 |
| 8 | pg_trgm 扩展 | 扩展 | 三 |

## 附录 E：废弃文件清单

| # | 文件 | 原因 | 阶段 |
|---|------|------|------|
| 1 | tools/code_executor.py（execute_python 工具） | terminal + execute_code 替代 | 一（废弃使用，四删除代码） |
| 2 | services/scheduler/service.py（APScheduler） | pg_cron 替代 | 一（废弃使用，四删除代码） |
| 3 | tools/memory_tools.py | PG 驱动记忆替代 | 二 |
| 4 | skills/markdown_skill.py | PG 驱动 Skill 替代 | 二 |
| 5 | skills/base.py | PG 驱动 Skill 替代 | 二 |
| 6 | agents/supervisor.py | AgentLoop 替代 | 二 |
| 7 | agents/manager.py | AgentLoop 替代 | 二 |
| 8 | graph/multi_agent_graph.py | AgentLoop 替代 | 二 |
| 9 | tools/handoff_tools.py | delegate_task 替代 | 四 |
| 10 | tools/time_tools.py | terminal("date") 替代 | 四 |