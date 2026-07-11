"""预置投资领域 Skill —— 10+ 个核心 Skill。

借鉴 Hermes 的 SKILL.md 格式，但用 PG 驱动。
这些 Skill 在 Agent 首次启动时自动创建，让 Agent 启动即懂业务。
"""
from alpha_agent.infra.skill_store import skill_store
from alpha_agent.utils.logger import logger

PRESET_SKILLS = [
    {
        "name": "data-sync-full",
        "display_name": "全量数据同步",
        "category": "data-sync",
        "description": "一键同步所有金融数据：股票列表、K线、财务、ETF、资金流向、行业聚合、宏观数据、因子计算",
        "trigger_keywords": ["同步数据", "全量同步", "更新数据", "数据同步", "sync all", "download data"],
        "content": """# 全量数据同步 (data-sync-full)

**目标：** 一键同步所有金融数据到本地数据库。

**使用场景：**
- 数据库为空或数据不完整
- 需要更新所有数据至最新
- 定期维护（建议每日收盘后执行）

## 执行步骤

1. 调用 `terminal(command="python scripts/sync_all_data.py", background=True)` 后台执行全量同步
2. 使用 `process(list)` 查看同步进度
3. 同步完成后使用 `execute_pipeline("data_health_check")` 验证数据完整性

## 注意事项

- 全量同步耗时较长（约 30-60 分钟），建议后台执行
- 同步前确认网络连接和数据源可用性
- 同步完成后建议运行 data_health_check 验证
""",
    },
    {
        "name": "data-sync-incremental",
        "display_name": "增量数据同步",
        "category": "data-sync",
        "description": "仅同步最近 N 天的增量数据，快速更新",
        "trigger_keywords": ["增量同步", "更新最近数据", "快速同步", "incremental sync"],
        "content": """# 增量数据同步 (data-sync-incremental)

**目标：** 快速同步最近的数据，避免全量同步的时间开销。

**使用场景：**
- 数据库已有数据，仅需更新最新几天
- 盘中快速刷新数据
- 数据出现短暂缺失

## 执行步骤

1. 调用 `terminal(command="python scripts/sync_stock_kline.py", background=True)` 同步最新K线
2. 调用 `terminal(command="python scripts/sync_money_flow.py", background=True)` 同步资金流向
3. 调用 `terminal(command="python scripts/calc_stock_factors.py", background=True)` 更新因子

## 注意事项

- 增量同步约 5-15 分钟完成
- 如果数据缺失超过 30 天，建议使用全量同步
""",
    },
    {
        "name": "data-health-check",
        "display_name": "数据健康检查",
        "category": "maintenance",
        "description": "检查数据库中各表的数据完整性、新鲜度和一致性",
        "trigger_keywords": ["数据检查", "健康检查", "数据完整性", "数据验证", "health check", "data check"],
        "content": """# 数据健康检查 (data-health-check)

**目标：** 检查数据库中所有数据表的状态，确保数据完整可用。

**使用场景：**
- 数据同步完成后验证
- 分析前确认数据质量
- 定期巡检（建议每周一次）

## 执行步骤

1. 调用 `execute_pipeline("data_health_check")` 执行健康检查
2. 检查输出中的各项指标：
   - 股票列表数量
   - K线数据最新日期
   - 财务数据覆盖范围
   - 因子数据完整性
3. 如有问题，使用 `skill_manage(action="search", query="data")` 查找修复方案

## 注意事项

- 健康检查不修改数据，仅诊断
- 发现数据缺失时，联系数据工程师或使用 data_auto_repair
""",
    },
    {
        "name": "data-auto-repair",
        "display_name": "数据自动修复",
        "category": "maintenance",
        "description": "自动诊断数据问题并生成修复方案",
        "trigger_keywords": ["数据修复", "修复数据", "数据问题", "repair data", "fix data", "数据缺失"],
        "content": """# 数据自动修复 (data-auto-repair)

**目标：** 自动诊断数据问题，生成修复方案，并执行修复。

**使用场景：**
- 数据健康检查发现异常
- 分析过程中发现数据缺失
- 数据同步失败后重试

## 执行步骤

1. 调用 `execute_pipeline("data_auto_repair")` 诊断数据问题
2. 根据诊断结果，执行对应的修复脚本：
   - K线缺失 → `terminal("python scripts/sync_stock_kline.py", background=True)`
   - 财务数据缺失 → `terminal("python scripts/sync_financial_data.py", background=True)`
   - 因子缺失 → `terminal("python scripts/calc_stock_factors.py", background=True)`
3. 修复后再次运行 `execute_pipeline("data_health_check")` 验证

## 注意事项

- 修复后务必验证数据完整性
- 如果修复失败，可能需要检查数据源或网络连接
""",
    },
    {
        "name": "stock-full-analysis",
        "display_name": "个股综合分析",
        "category": "analysis",
        "description": "对指定股票执行基本面+技术面+风险控制的全面分析",
        "trigger_keywords": ["分析股票", "个股分析", "股票分析", "全面分析", "stock analysis", "analyze stock"],
        "content": """# 个股综合分析 (stock-full-analysis)

**目标：** 对指定股票执行全面的投资分析，给出综合评级。

**使用场景：**
- 用户询问某只股票的投资价值
- 需要基本面、技术面、风险多维评估
- 投资决策前的研究

## 执行步骤

1. 确保数据完整：`execute_pipeline("data_health_check")`
2. 执行综合分析 Pipeline：`execute_pipeline("stock_analysis", {"ts_code": "目标股票代码"})`
3. 解读分析结果，包含：
   - 基本面：估值、盈利、成长性
   - 技术面：趋势、指标、支撑阻力
   - 风险：波动率、回撤、仓位建议
4. 给出综合评级：强烈买入/买入/持有/卖出/强烈卖出

## 注意事项

- 股票代码格式：000001.SZ（深圳）或 600000.SH（上海）
- 分析结果仅供参考，不构成投资建议
- 投资有风险，入市需谨慎
""",
    },
    {
        "name": "stock-screening-daily",
        "display_name": "每日选股",
        "category": "analysis",
        "description": "基于多因子模型筛选优质股票，支持按评分和行业筛选",
        "trigger_keywords": ["选股", "筛选股票", "股票筛选", "找好股票", "stock screening", "screen stocks"],
        "content": """# 每日选股 (stock-screening-daily)

**目标：** 基于综合评分因子，筛选出当前最具投资价值的股票。

**使用场景：**
- 每日开盘前选股
- 构建投资组合的候选池
- 寻找潜在投资机会

## 执行步骤

1. 确保因子数据是最新的：`terminal("python scripts/calc_stock_factors.py", background=True)`
2. 执行选股 Pipeline：`execute_pipeline("stock_screening", {"min_score": 50, "top_n": 10})`
3. 对结果中的 Top 股票执行 `execute_pipeline("stock_analysis", {"ts_code": "TOP股票代码"})` 深度分析
4. 汇总选股结果，给出推荐列表

## 参数说明

- min_score: 最低综合评分（默认 50，范围 0-100）
- top_n: 返回前 N 只股票（默认 10）

## 注意事项

- 选股前确保因子数据已更新
- 选股结果需要结合市场环境和个人风险偏好
- 建议对选股结果做进一步的基本面分析
""",
    },
    {
        "name": "factor-backtest-daily",
        "display_name": "因子回测",
        "category": "analysis",
        "description": "对选股因子进行 history 回测，评估策略绩效",
        "trigger_keywords": ["回测", "因子回测", "策略回测", "backtest", "因子绩效", "策略评估"],
        "content": """# 因子回测 (factor-backtest-daily)

**目标：** 对选股因子执行 history 回测，评估策略的历史表现。

**使用场景：**
- 验证因子有效性
- 评估策略的历史绩效
- 对比不同因子的表现

## 执行步骤

1. 执行因子回测：`execute_pipeline("factor_backtest", {"factor": "composite_score", "top_n": 20, "lookback_days": 60})`
2. 分析回测结果：
   - 组合平均收益率
   - 波动率
   - 夏普比率（近似）
   - 最大回撤
3. 如需对比不同因子，修改 factor 参数重复执行

## 参数说明

- factor: 因子名称（composite_score/momentum/volatility）
- top_n: 持仓股票数（默认 20）
- lookback_days: 回测天数（默认 60）

## 注意事项

- 历史回测不代表未来表现
- 注意回测中的幸存者偏差
- 建议结合多种因子综合评估
""",
    },
    {
        "name": "portfolio-build-daily",
        "display_name": "组合构建",
        "category": "analysis",
        "description": "基于选股结果构建投资组合，包含权重优化和风控检查",
        "trigger_keywords": ["构建组合", "投资组合", "组合构建", "portfolio", "仓位配置", "权重"],
        "content": """# 组合构建 (portfolio-build-daily)

**目标：** 基于选股结果，构建优化后的投资组合，包含风控检查。

**使用场景：**
- 用户需要构建投资组合
- 调整现有组合的仓位
- 定期再平衡

## 执行步骤

1. 先执行选股：`execute_pipeline("stock_screening", {"min_score": 50, "top_n": 20})`
2. 构建组合：`execute_pipeline("portfolio_build", {"min_score": 50, "max_stocks": 10, "weight_strategy": "score_weight"})`
3. 检查风控输出：
   - 单票权重是否超限
   - 行业集中度是否过高
4. 如有风控警告，调整参数重新构建

## 参数说明

- min_score: 最低综合评分（默认 50）
- max_stocks: 最大持仓数（默认 10）
- weight_strategy: 权重策略（equal_weight/score_weight）
- max_single_weight: 单票最大权重（默认 0.3）
- max_industry_weight: 单行业最大权重（默认 0.5）

## 注意事项

- 组合构建是投资决策的起点，不是终点
- 实际投资中需考虑流动性、交易成本等因素
- 建议定期（每周/每月）再平衡
""",
    },
    {
        "name": "market-overview-daily",
        "display_name": "市场全景",
        "category": "analysis",
        "description": "获取市场全景数据，包括主要指数、涨跌幅分布、异常检测",
        "trigger_keywords": ["市场", "大盘", "市场概况", "market", "指数", "市场全景", "市场行情"],
        "content": """# 市场全景 (market-overview-daily)

**目标：** 获取市场全景快照，了解整体市场状态。

**使用场景：**
- 每日开盘前了解市场环境
- 判断市场整体情绪
- 发现异常波动

## 执行步骤

1. 执行市场全景：`execute_pipeline("market_overview")`
2. 解读关键指标：
   - 主要指数涨跌
   - 涨跌家数分布
   - 成交额变化
   - 异常股票检测
3. 基于市场状态调整投资策略

## 注意事项

- 市场全景是分析的基础，不是决策的唯一依据
- 注意区分市场正常波动和异常信号
- 结合宏观经济数据综合判断
""",
    },
    {
        "name": "industry-rotation",
        "display_name": "行业轮动分析",
        "category": "analysis",
        "description": "分析行业资金流向和轮动趋势，辅助行业配置决策",
        "trigger_keywords": ["行业轮动", "行业分析", "行业配置", "板块轮动", "industry", "sector"],
        "content": """# 行业轮动分析 (industry-rotation)

**目标：** 分析行业资金流向和轮动趋势，识别强势行业。

**使用场景：**
- 行业配置决策
- 识别市场热点
- 行业 ETF 投资

## 执行步骤

1. 查询行业聚合数据：`query_data("SELECT industry, AVG(pct_chg) as avg_chg, SUM(amount) as total_amount FROM daily_kline d JOIN stocks s ON d.ts_code = s.ts_code WHERE d.trade_date = (SELECT MAX(trade_date) FROM daily_kline) GROUP BY industry ORDER BY avg_chg DESC")`
2. 查询资金流向：`query_data("SELECT * FROM money_flow WHERE trade_date = (SELECT MAX(trade_date) FROM money_flow) ORDER BY main_net_inflow DESC LIMIT 10")`
3. 分析行业轮动趋势，给出配置建议

## 注意事项

- 行业轮动需要多日数据验证趋势
- 注意区分短期炒作和长期趋势
- 建议结合基本面验证行业景气度
""",
    },
    {
        "name": "risk-assessment",
        "display_name": "风险评估",
        "category": "analysis",
        "description": "对单只股票或投资组合进行全面的风险评估",
        "trigger_keywords": ["风险", "风险评估", "风险分析", "risk", "风控", "回撤", "波动"],
        "content": """# 风险评估 (risk-assessment)

**目标：** 对投资标的进行全面的风险评估。

**使用场景：**
- 投资前评估风险水平
- 组合风险管理
- 止损点设置

## 执行步骤

1. 查询波动率数据：`query_data("SELECT ts_code, volatility_20d, amplitude_avg_20d, rsi_14 FROM stock_factors WHERE ts_code IN ('目标股票代码') ORDER BY ts_code")`
2. 查询历史回撤：`query_data("SELECT ts_code, MIN(pct_chg) as max_daily_loss, STDDEV(pct_chg) as daily_volatility FROM daily_kline WHERE ts_code IN ('目标股票代码') AND trade_date >= (SELECT MAX(trade_date) FROM daily_kline) - 60 GROUP BY ts_code")`
3. 如果有组合，使用 `get_portfolio_risk` 和 `get_portfolio_summary` 工具
4. 给出风险评级和建议仓位

## 风险评估维度

- 波动率：日收益率标准差
- 最大回撤：历史最大连续亏损
- RSI：超买超卖信号
- Beta：相对市场敏感度
- 仓位建议：基于风险承受能力

## 注意事项

- 风险评估是概率性的，不是确定性的
- 过去的风险不代表未来的风险
- 建议设置止损位控制风险
""",
    },
    {
        "name": "news-sentiment",
        "display_name": "新闻舆情分析",
        "category": "analysis",
        "description": "获取股票相关新闻和公告，分析市场情绪",
        "trigger_keywords": ["新闻", "公告", "舆情", "消息", "news", "sentiment", "利好", "利空"],
        "content": """# 新闻舆情分析 (news-sentiment)

**目标：** 获取和分析股票相关新闻，评估市场情绪。

**使用场景：**
- 重大事件前后的市场反应分析
- 日常舆情监控
- 公告解读

## 执行步骤

1. 获取新闻：使用 `get_stock_news` 工具获取目标股票新闻
2. 获取公告：使用 `get_stock_announcement` 工具获取公告信息
3. 搜索相关资讯：使用 `web_search` 搜索最新相关消息
4. 综合分析：
   - 正面/负面/中性新闻比例
   - 关键事件影响评估
   - 市场预期变化

## 注意事项

- 新闻情绪分析需要结合价格走势验证
- 注意区分真实新闻和谣言
- 公告信息需要专业解读，建议结合基本面分析
""",
    },
]

def seed_preset_skills() -> int:
    """将预置 Skill 写入数据库。幂等：已存在的 Skill 不会重复创建。"""
    created = 0
    skipped = 0

    for skill_data in PRESET_SKILLS:
        name = skill_data["name"]
        existing = skill_store.get_skill(name)
        if existing:
            logger.info(f"[PresetSkills] Skill '{name}' already exists, skipping")
            skipped += 1
            continue

        try:
            skill_store.create_skill(
                name=name,
                content=skill_data["content"],
                category=skill_data["category"],
                description=skill_data["description"],
                trigger_keywords=skill_data["trigger_keywords"],
                display_name=skill_data["display_name"],
                source="preset",
                created_by="system",
                metadata={
                    "preset": True,
                    "version": "1.0",
                },
            )
            created += 1
            logger.info(f"[PresetSkills] Created preset skill: {name}")
        except Exception as e:
            logger.error(f"[PresetSkills] Failed to create '{name}': {e}")

    logger.info(f"[PresetSkills] Seeding complete: {created} created, {skipped} skipped")
    return created

if __name__ == "__main__":
    seed_preset_skills()