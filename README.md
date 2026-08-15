# Alpha Agent

> 借鉴 Hermes 核心能力，专注投资分析领域的 AgentLoop 智能体

基于 LangGraph 的 AgentLoop 持久循环架构，单 Agent 拥有全部核心工具，自主决策调用链。继承 Hermes 的 terminal/process/execute_code/delegate_task/skill_manage/Closed Learning Loop 核心能力，同时用投资领域专注构建专业深度。

---

## 架构

```
                       用户输入（自然语言）
                              │
                              ▼
                    ┌─────────────────┐
                    │   AgentLoop      │
                    │   持久循环 + 工具  │
                    └───────┬─────────┘
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
   ┌──────────┐     ┌──────────┐      ┌──────────────┐
   │ terminal  │     │  process │      │ execute_code │
   │ 执行命令   │     │ 进程管理  │      │ 代码压缩执行  │
   └──────────┘     └──────────┘      └──────────────┘
         │                  │                  │
         ▼                  ▼                  ▼
   ┌──────────┐     ┌──────────┐      ┌──────────────┐
   │delegate  │     │ pipeline │      │ skill_manage │
   │子Agent委派│     │ 分析工作流 │      │ 技能管理     │
   └──────────┘     └──────────┘      └──────────────┘
         │                  │                  │
         ▼                  ▼                  ▼
   ┌──────────────────────────────────────────────────┐
   │              投资分析 Pipeline（7 个）               │
   │  stock_analysis / market_overview / stock_screening│
   │  factor_backtest / portfolio_build / data_health   │
   │              data_auto_repair                      │
   └──────────────────────────────────────────────────┘
         │
         ▼
   ┌──────────────────────────────────────────────────┐
   │              Closed Learning Loop                 │
   │    每轮对话后自动评分 → 沉淀 Skill → 越用越聪明    │
   └──────────────────────────────────────────────────┘
```

**核心设计理念**：用户说"同步数据"就不用管，Agent 自主完成闭环。不预设"什么问题该谁答"，Agent 根据工具能力自主决策。

---

## 快速开始

### 1. 环境要求

- Python >= 3.10
- PostgreSQL（可选，用于数据存储）
- Redis（可选，用于缓存）

### 2. 安装

```bash
cd alpha-agent
pip install -e ".[dev]"
```

### 3. 配置

```bash
cp .env.example .env
```

**.env 关键配置**：

```env
# LLM 配置（必填）
LLM_PROVIDER=openai
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

# PostgreSQL（可选）
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=alpha_agent
```

---

## 运行

### CLI 交互模式

```bash
# 启动 AgentLoop 交互对话
python -m alpha_agent.cli

# 自然语言提问，Agent 自主完成分析
你 > 帮我分析一下平安银行
你 > 今天市场整体怎么样
你 > 帮我选5只强势股
你 > 按20日涨跌幅排名
你 > 行业轮动分析
你 > 同步K线数据
```

### CLI 单次查询

```bash
# 直接传入问题，Agent 执行后退出
python -m alpha_agent.cli "分析平安银行的基本面和技术面"
python -m alpha_agent.cli "检查数据健康状态"
python -m alpha_agent.cli "列出所有可用的技术因子"
```

### 内置快捷键

| 命令 | 说明 |
|------|------|
| `/help` `/h` | 显示帮助 |
| `/clear` `/c` | 清空对话历史 |
| `/tasks` | 查看后台任务 |
| `/exit` `/quit` | 退出 |

---

### API 服务

```bash
python -m alpha_agent.api
# 访问 http://localhost:8000/docs 查看 Swagger 文档
```

**API 端点**：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/chat/stream` | POST | 流式对话（SSE） |
| `/api/conversations` | GET | 获取对话列表 |
| `/api/conversations/{id}` | GET | 获取对话详情 |
| `/api/conversations/{id}` | DELETE | 删除对话 |
| `/api/tracer/stats` | GET | 追踪统计 |
| `/api/tracer/traces` | GET | 最近追踪记录 |

**API 调用示例**：

```python
import requests

url = "http://localhost:8000/api/chat/stream"
resp = requests.post(url, json={
    "thread_id": "my-session",
    "message": "分析茅台的基本面和技术面",
    "mode": "agent_loop"
}, stream=True)
for line in resp.iter_lines():
    if line:
        print(line.decode("utf-8"))
```

---

### 数据同步

通过自然语言让 Agent 同步数据，Agent 后台执行不阻塞：

```bash
# 交互模式下直接说
你 > 同步股票列表和K线数据

# 或单次查询
python -m alpha_agent.cli "同步全量数据"
```

也可以直接运行脚本：

```bash
python scripts/sync_all_data.py              # 一键全量同步
python scripts/sync_stock_list.py            # 股票列表
python scripts/sync_stock_kline.py           # 全量K线
python scripts/sync_stock_kline.py 000001.SZ # 指定股票K线
python scripts/sync_etf_data.py              # ETF数据
python scripts/sync_financial_data.py        # 财务数据
python scripts/sync_money_flow.py            # 资金流向
python scripts/sync_industry_agg.py          # 行业聚合
python scripts/sync_macro_data.py            # 宏观数据
python scripts/calc_stock_factors.py         # 计算选股因子
```

---

### 测试

```bash
pytest
pytest --cov=alpha_agent
```

---

## 核心能力

### 工具体系（~30 个工具）

| 分类 | 工具 | 说明 |
|------|------|------|
| **核心执行** | `terminal` | 前台/后台执行任意命令 |
| | `process` | 后台进程管理（poll/wait/kill/log） |
| | `execute_code` | 多步工作流压缩为一次调用 |
| | `execute_pipeline` | 执行预置分析 Pipeline |
| | `delegate_task` | 动态创建子 Agent，加载 Profile |
| | `skill_manage` | 技能全生命周期管理 |
| **数据查询** | `get_database_schema` | 查看数据库表结构 |
| | `get_current_time` | 获取当前时间 |
| | `web_search` | 搜索外部信息 |
| **市场分析** | `screen_stocks` | 全市场选股/ETF扫描 |
| | `get_factor_ranking` | 因子排名 |
| | `get_industry_rotation` | 行业轮动分析 |
| | `get_stock_factors` | 获取股票因子数据 |
| | `get_macro_data` | 宏观数据查询 |
| | `get_money_flow` | 资金流向 |
| **回测对比** | `run_backtest` | 策略回测 |
| | `run_factor_backtest` | 因子策略回测 |
| | `compare_stocks` | 多股对比分析 |
| **组合管理** | `create_portfolio` | 创建组合 |
| | `get_portfolio_summary` | 组合概览 |
| | `get_portfolio_risk` | 风险评估 |
| | `get_rebalance_suggestion` | 调仓建议 |
| **监控图表** | `get_realtime_quote` | 实时行情 |
| | `add_price_alert` / `check_alerts` | 价格告警 |
| | `generate_chart` | 图表可视化 |
| **智能分析** | `detect_anomalies` | 异常检测 |
| | `attribute_analysis` | 归因分析 |
| | `analyze_trend` | 趋势分析 |

### Pipeline 分析工作流（7 个）

| Pipeline | 流程 |
|----------|------|
| `stock_analysis` | 基本面 → 技术面 → 风控 → 综合评级 → 报告 |
| `market_overview` | 行情统计 → 行业涨跌 → 资金流向 → 异常检测 → 报告 |
| `stock_screening` | 标的池 → 因子计算 → 排名筛选 → 输出 |
| `factor_backtest` | 选股 → 因子构建 → 回测 → 绩效评估 |
| `portfolio_build` | 选股 → 权重优化 → 风控检查 → 组合构建 |
| `data_health_check` | 全表扫描 → 缺失检测 → 新鲜度评估 → 修复建议 |
| `data_auto_repair` | 诊断 → 重试/切换源 → 补数据 → 验证 → 沉淀 Skill |

### Profile 系统（5 个）

| Profile | 专长 |
|---------|------|
| `fundamental_analyst` | 基本面分析 |
| `technical_analyst` | 技术面分析 |
| `risk_controller` | 风险控制 |
| `data_engineer` | 数据工程 |
| `backtest_engineer` | 策略回测 |

### 技能系统

- **PG 驱动**：Skill 持久化存储，JSONB 索引 + 全文搜索
- **闭环学习**：每轮对话后自动评分，满足条件自动沉淀 Skill
- **预置技能**：12 个投资领域核心 Skill（数据同步、健康检查、个股分析、选股、回测等）

### 记忆系统

三层记忆模型（PG 驱动）：

| 层级 | 说明 |
|------|------|
| Frozen Memory | 持久的用户画像、偏好、知识 |
| Episodic Memory | 会话级经验片段（30 天自动过期） |
| SkillRef Memory | 成功使用的 Skill 引用 |

---

## 项目结构

```
alpha-agent/
├── src/
│   └── alpha_agent/          # Python 包
│       ├── core/             # AgentLoop + Learning Loop
│       │   ├── agent_loop.py     # 单 Agent 持久循环
│       │   └── learning_loop.py  # 闭环学习（自动沉淀 Skill）
│       ├── tools/            # 工具体系
│       │   ├── core/             # 核心工具（terminal/process/execute_code/delegate/pipeline/skill_manage）
│       │   ├── analysis/         # 分析工具（回测/对比/因子/选股/洞察/归因/知识图谱）
│       │   ├── market/           # 市场工具（行情/新闻/监控/宏观）
│       │   ├── data/             # 数据工具（查询/时间/搜索）
│       │   ├── portfolio/        # 组合工具
│       │   └── viz/              # 可视化工具
│       ├── pipeline/         # 分析 Pipeline（7 个预置工作流）
│       ├── infra/            # 基础设施
│       │   ├── db/               # 数据库（SQLAlchemy + PostgreSQL）
│       │   ├── llm/              # LLM 服务
│       │   ├── sync/             # 数据同步
│       │   ├── skill_store.py    # Skill 存储（PG）
│       │   ├── memory_store.py   # 记忆存储（PG）三层记忆
│       │   ├── process_registry.py # 进程注册表
│       │   ├── profile_loader.py # Profile 加载器
│       │   ├── catalog.py        # 数据目录
│       │   └── schema_provider.py # Schema 提供器
│       ├── domain/           # 领域服务
│       │   ├── market/           # 行情数据（AkShare/BaoStock/Tushare）
│       │   ├── factor/           # 因子计算
│       │   ├── factors/          # 技术因子库
│       │   ├── screener/         # 选股扫描
│       │   ├── rotation/         # 行业轮动
│       │   ├── backtest/         # 策略回测
│       │   ├── portfolio/        # 组合管理
│       │   ├── comparison/       # 对比分析
│       │   ├── monitor/          # 价格监控
│       │   └── quant/            # 量化引擎
│       ├── api/              # FastAPI 服务
│       ├── utils/            # 工具（logger/tracer/executor）
│       ├── cli.py            # CLI 统一入口
│       └── config.py         # 配置管理
├── profiles/                 # Agent Profile（YAML）
├── skills/                   # 预置 Skill（Markdown）
├── scripts/                  # 数据同步脚本
├── storage/                  # 数据库迁移
├── tests/                    # 测试
├── frontend/                 # 前端（React + TypeScript + Vite）
└── pyproject.toml
```

---

## License

MIT