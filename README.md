# Investment Agent

基于 LangGraph 的多 Agent 金融分析智能体，投资研究总监（Supervisor）协调 9 个专业分析师，支持多轮辩论、数据同步、策略回测、LLM 智能路由和 Worker 间任务交接。

## 架构

```
                    用户输入
                       │
                       ▼
              ┌─────────────────┐
              │  SupervisorAgent  │  ← LLM 智能路由 + 综合
              │  (投资研究总监)    │
              └───────┬───────────┘
                      │
     ┌────────────────┼────────────────┐
     ▼                ▼                ▼
┌──────────┐  ┌──────────┐  ┌──────────┐
│ 基本面分析师│  │ 技术面分析师│  │  风控官    │  ANALYSIS 类
└──────────┘  └──────────┘  └──────────┘
     │                │                │
     ▼                ▼                ▼
┌──────────┐  ┌──────────┐  ┌──────────┐
│ 多头分析师  │  │ 空头分析师  │  │ 辩论评审员  │  DEBATE 类
└──────────┘  └──────────┘  └──────────┘
     │                │                │
     ▼                ▼                ▼
┌──────────┐  ┌──────────┐  ┌──────────┐
│ 数据采集员  │  │ 回测工程师  │  │ 研报解读员  │  RESEARCH 类
└──────────┘  └──────────┘  └──────────┘
                      │
                      ▼
              ┌─────────────────┐
              │ 数据同步工程师    │  RESEARCH 类
              └─────────────────┘
```

## 快速开始

### 1. 环境要求

- Python >= 3.10
- PostgreSQL（可选，用于数据存储）
- Redis（可选，用于缓存）

### 2. 安装

```bash
# 克隆项目
cd alpha-agent

# 安装依赖
pip install -e .
```

### 3. 配置

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env，配置 LLM（必填）
```

**.env 关键配置**：

```env
# LLM 配置（必填）
LLM_PROVIDER=openai
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_ENABLED=true

# PostgreSQL（可选，不配置则降级为无 DB 模式）
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=alpha_agent
```

## 运行命令

> 所有命令必须在项目根目录 `alpha-agent/` 下执行，不是在 `alpha_agent/` 子目录。

### CLI 交互模式

```bash
# 切换到项目根目录
cd alpha-agent

# 单 Agent 交互模式（ReAct）
python -m alpha_agent.cli

# 多 Agent 协作模式（Supervisor + 9 个 Worker）
python -m alpha_agent.cli -m

# 帮助
python -m alpha_agent.cli --help
```

### CLI 单次查询

```bash
# 单 Agent 单次查询
python -m alpha_agent.cli -q "分析茅台"

# 多 Agent 单次查询（含 LLM 智能路由）
python -m alpha_agent.cli -m -q "分析茅台的基本面和技术面"

# 指定股票代码
python -m alpha_agent.cli -m -q "分析这只股票" -c 000001.SZ

# 数据同步
python -m alpha_agent.cli -m -q "同步股票列表"
```

### API 服务

```bash
# 启动 API 服务
python -m alpha_agent.api
# 访问 http://localhost:8000/docs 查看 Swagger 文档
```

**API 端点**：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/chat/stream` | POST | 流式对话（支持 ReAct 和 Multi-Agent） |
| `/api/conversations` | GET | 获取对话列表 |
| `/api/conversations/{id}` | GET | 获取对话详情 |
| `/api/conversations/{id}` | DELETE | 删除对话 |
| `/api/tracer/stats` | GET | 追踪统计（LLM 调用、工具调用、延迟等） |
| `/api/tracer/traces` | GET | 最近追踪记录 |

**API 调用示例**：

```python
import requests
import json

url = "http://localhost:8000/api/chat/stream"
data = {
    "thread_id": "my-session",
    "message": "分析茅台的基本面和技术面",
    "mode": "multi_agent"        # react 或 multi_agent
}
resp = requests.post(url, json=data, stream=True)
for line in resp.iter_lines():
    if line:
        print(line.decode("utf-8"))
```

### 数据同步

```bash
# 一键全量同步
python scripts/sync_all_data.py

# 同步股票列表
python scripts/sync_stock_list.py

# 同步全部股票日K线
python scripts/sync_stock_kline.py

# 同步指定股票K线
python scripts/sync_stock_kline.py 000001.SZ

# 同步ETF数据
python scripts/sync_etf_data.py

# 同步财务数据
python scripts/sync_financial_data.py

# 同步资金流向
python scripts/sync_money_flow.py

# 同步行业聚合
python scripts/sync_industry_agg.py

# 同步宏观数据
python scripts/sync_macro_data.py

# 计算选股因子
python scripts/calc_stock_factors.py
```

### 定时调度

```bash
# 在 .env 中启用调度器
SCHEDULER_ENABLED=true

# 启动后会按 cron 表达式自动执行：
#   股票列表同步：工作日 8:00
#   股票K线同步：工作日 17:00
#   ETF 列表同步：工作日 8:00
#   ETF K线同步： 工作日 17:30
```

### 测试

```bash
# 运行所有测试
pytest

# 运行指定测试
pytest tests/test_graph.py

# 带覆盖率
pytest --cov=alpha_agent
```

## CLI 交互命令

| 命令 | 说明 |
|------|------|
| `/help` `/h` | 显示帮助 |
| `/clear` `/c` | 清空对话历史 |
| `/history` | 查看对话历史 |
| `/analyze <code>` | 分析一只股票 |
| `/multi` | 切换到多 Agent 模式 |
| `/reAct` | 切换回单 Agent 模式 |
| `/screen [stock\|etf]` | 全市场选股 |
| `/factor <name>` | 因子排名 |
| `/factors` | 列出所有因子 |
| `/rotation` | 行业轮动分析 |
| `/fbt <codes>` | 因子策略回测 |
| `/exit` `/quit` `/q` | 退出 |

## 内置追踪器

完全免费的 LLM 调用可观测性方案，替代 LangSmith/LangFuse。

```bash
# 查看统计
curl http://localhost:8000/api/tracer/stats?days=7

# 查看最近追踪记录
curl http://localhost:8000/api/tracer/traces?limit=50
```

数据存储在 `data/traces/trace_YYYY-MM-DD.jsonl`，30 天自动清理。

## 项目结构

```
alpha_agent/
├── agents/          # Multi-Agent 系统（Supervisor + 9 Workers）
│   ├── supervisor.py    # SupervisorAgent（LLM 路由 + 综合）
│   ├── base.py          # BaseWorker 抽象基类
│   ├── manager.py       # WorkerManager（注册、路由）
│   ├── workers.py       # 基本面/技术面/风控 Worker
│   ├── debate.py        # 多空辩论 Worker + Judge
│   ├── research.py      # 数据采集/回测/研报 Worker
│   └── sync_worker.py   # 数据同步 Worker
├── api/             # FastAPI 服务
│   ├── main.py          # API 路由
│   └── schemas.py       # 请求/响应模型
├── services/        # 业务服务层
│   ├── data_sync/       # 数据同步服务
│   ├── market/          # 行情数据服务（AkShare/BaoStock）
│   ├── llm/             # LLM 服务
│   ├── screener/        # 选股服务
│   ├── factor/          # 因子服务
│   ├── rotation/        # 行业轮动服务
│   ├── backtest/        # 回测服务
│   ├── portfolio/       # 组合管理服务
│   ├── comparison/      # 对比分析服务
│   ├── monitor/         # 价格监控服务
│   └── scheduler/       # 定时调度服务
├── tools/           # LangChain 工具集（~20 个工具）
├── storage/         # 数据持久化（PostgreSQL + Redis）
├── graph/           # LangGraph 图定义
├── quant/           # 量化策略引擎
├── factors/         # 技术因子库
├── utils/           # 工具（logger、tracer）
├── cli.py           # 命令行入口
└── config.py        # 配置管理
```

## License

MIT