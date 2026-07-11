from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from alpha_agent.infra.db.database import Base, TimestampMixin


class Stock(Base, TimestampMixin):
    """股票基本信息表，存储所有上市股票的基本信息"""
    __tablename__ = "stocks"
    __table_args__ = {"comment": "股票基本信息表，存储所有上市股票的基本信息"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    ts_code: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False, comment="股票代码（如000001.SZ）")
    symbol: Mapped[str] = mapped_column(String(20), index=True, comment="交易代码（如000001）")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="股票名称")
    area: Mapped[str] = mapped_column(String(50), default="", comment="所在地区")
    industry: Mapped[str] = mapped_column(String(50), default="", comment="所属行业")
    market: Mapped[str] = mapped_column(String(20), default="", comment="交易市场")
    list_date: Mapped[str] = mapped_column(String(10), default="", comment="上市日期")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否活跃")


class DailyKline(Base, TimestampMixin):
    """股票日K线行情表，每只股票每个交易日一条记录"""
    __tablename__ = "daily_kline"
    __table_args__ = {"comment": "股票日K线行情表，每只股票每个交易日一条记录"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    ts_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False, comment="股票代码")
    trade_date: Mapped[str] = mapped_column(String(10), index=True, nullable=False, comment="交易日期（YYYYMMDD）")
    open: Mapped[float] = mapped_column(Numeric(12, 3), comment="开盘价")
    high: Mapped[float] = mapped_column(Numeric(12, 3), comment="最高价")
    low: Mapped[float] = mapped_column(Numeric(12, 3), comment="最低价")
    close: Mapped[float] = mapped_column(Numeric(12, 3), comment="收盘价")
    pre_close: Mapped[float] = mapped_column(Numeric(12, 3), default=0, comment="前收盘价")
    change: Mapped[float] = mapped_column(Numeric(12, 3), default=0, comment="涨跌额")
    pct_chg: Mapped[float] = mapped_column(Numeric(10, 3), default=0, comment="涨跌幅（%）")
    vol: Mapped[float] = mapped_column(Numeric(20, 2), default=0, comment="成交量（手）")
    amount: Mapped[float] = mapped_column(Numeric(20, 2), default=0, comment="成交额（万元）")

    __mapper_args__ = {
        "primary_key": ["ts_code", "trade_date"],
    }


class FinancialReport(Base, TimestampMixin):
    """财务报表表，存储公司定期财务报告"""
    __tablename__ = "financial_reports"
    __table_args__ = {"comment": "财务报表表，存储公司定期财务报告"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    ts_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False, comment="股票代码")
    end_date: Mapped[str] = mapped_column(String(10), index=True, nullable=False, comment="报告期截止日")
    report_type: Mapped[str] = mapped_column(String(20), default="", comment="报告类型")
    total_revenue: Mapped[float] = mapped_column(Numeric(20, 2), default=0, comment="营业总收入")
    net_profit: Mapped[float] = mapped_column(Numeric(20, 2), default=0, comment="净利润")
    eps: Mapped[float] = mapped_column(Numeric(12, 4), default=0, comment="每股收益")
    roe: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="净资产收益率")
    gross_margin: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="毛利率")
    net_margin: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="净利率")


class AnalysisRecord(Base, TimestampMixin):
    """分析记录表，存储历史分析任务和结果"""
    __tablename__ = "analysis_records"
    __table_args__ = {"comment": "分析记录表，存储历史分析任务和结果"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    request_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False, comment="请求唯一ID")
    ts_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False, comment="股票代码")
    analysis_type: Mapped[str] = mapped_column(String(50), default="full", comment="分析类型（full/fundamental/technical/risk）")
    status: Mapped[str] = mapped_column(String(20), default="completed", comment="分析状态（pending/running/completed/failed）")

    final_rating: Mapped[str] = mapped_column(String(20), default="", comment="最终评级（强烈买入/买入/持有/卖出/强烈卖出）")
    final_score: Mapped[float] = mapped_column(Numeric(5, 2), default=0, comment="综合评分（0-100）")
    final_summary: Mapped[str] = mapped_column(Text, default="", comment="综合分析总结")

    fundamental_rating: Mapped[str] = mapped_column(String(20), default="", comment="基本面评级")
    fundamental_score: Mapped[float] = mapped_column(Numeric(5, 2), default=0, comment="基本面评分")
    fundamental_summary: Mapped[str] = mapped_column(Text, default="", comment="基本面分析总结")
    fundamental_detail = mapped_column(JSON, default=dict, comment="基本面分析详情（JSON）")

    technical_rating: Mapped[str] = mapped_column(String(20), default="", comment="技术面评级")
    technical_score: Mapped[float] = mapped_column(Numeric(5, 2), default=0, comment="技术面评分")
    technical_summary: Mapped[str] = mapped_column(Text, default="", comment="技术面分析总结")
    technical_detail = mapped_column(JSON, default=dict, comment="技术面分析详情（JSON）")

    risk_rating: Mapped[str] = mapped_column(String(20), default="", comment="风险评级（低风险/中风险/高风险）")
    risk_score: Mapped[float] = mapped_column(Numeric(5, 2), default=0, comment="风险评分（0-100）")
    risk_summary: Mapped[str] = mapped_column(Text, default="", comment="风险分析总结")
    risk_detail = mapped_column(JSON, default=dict, comment="风险分析详情（JSON）")

    signals = mapped_column(JSON, default=list, comment="交易信号列表（JSON）")
    suggested_position: Mapped[float] = mapped_column(Numeric(5, 3), default=0, comment="建议仓位（0-1）")


class Portfolio(Base, TimestampMixin):
    """投资组合表，存储用户创建的投资组合"""
    __tablename__ = "portfolios"
    __table_args__ = {"comment": "投资组合表，存储用户创建的投资组合"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    portfolio_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False, comment="组合唯一ID")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="组合名称")
    description: Mapped[str] = mapped_column(String(500), default="", comment="组合描述")
    owner_id: Mapped[str] = mapped_column(String(64), default="default", comment="所有者ID")
    benchmark: Mapped[str] = mapped_column(String(20), default="000300.SH", comment="基准指数（如000300.SH=沪深300）")
    initial_capital: Mapped[float] = mapped_column(Numeric(20, 2), default=100000.0, comment="初始资金")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否活跃")


class PortfolioPosition(Base, TimestampMixin):
    """组合持仓表，存储投资组合中的具体持仓"""
    __tablename__ = "portfolio_positions"
    __table_args__ = {"comment": "组合持仓表，存储投资组合中的具体持仓"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    portfolio_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False, comment="所属组合ID")
    ts_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False, comment="股票代码")
    stock_name: Mapped[str] = mapped_column(String(100), default="", comment="股票名称")
    shares: Mapped[int] = mapped_column(Integer, default=0, comment="持仓股数")
    cost_price: Mapped[float] = mapped_column(Numeric(12, 4), default=0.0, comment="成本价")
    current_price: Mapped[float] = mapped_column(Numeric(12, 4), default=0.0, comment="当前价")
    market_value: Mapped[float] = mapped_column(Numeric(20, 2), default=0.0, comment="持仓市值")
    weight: Mapped[float] = mapped_column(Numeric(5, 4), default=0.0, comment="持仓权重（0-1）")
    profit: Mapped[float] = mapped_column(Numeric(20, 2), default=0.0, comment="浮动盈亏")
    profit_pct: Mapped[float] = mapped_column(Numeric(10, 4), default=0.0, comment="盈亏比例（%）")
    industry: Mapped[str] = mapped_column(String(50), default="", comment="所属行业")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否活跃")


class Etf(Base, TimestampMixin):
    """ETF基本信息表，存储所有可交易ETF的基本信息"""
    __tablename__ = "etfs"
    __table_args__ = {"comment": "ETF基本信息表，存储所有可交易ETF的基本信息"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    ts_code: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False, comment="ETF代码")
    symbol: Mapped[str] = mapped_column(String(20), index=True, comment="交易代码")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="ETF名称")
    etf_type: Mapped[str] = mapped_column(String(30), default="", comment="ETF类型")
    issuer: Mapped[str] = mapped_column(String(100), default="", comment="发行人")
    index_code: Mapped[str] = mapped_column(String(20), default="", comment="跟踪指数代码")
    index_name: Mapped[str] = mapped_column(String(100), default="", comment="跟踪指数名称")
    list_date: Mapped[str] = mapped_column(String(10), default="", comment="上市日期")
    delist_date: Mapped[str] = mapped_column(String(10), default="", comment="退市日期")
    market: Mapped[str] = mapped_column(String(20), default="", comment="交易市场")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否活跃")


class EtfDailyKline(Base, TimestampMixin):
    """ETF日K线行情表"""
    __tablename__ = "etf_daily_kline"
    __table_args__ = {"comment": "ETF日K线行情表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    ts_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False, comment="ETF代码")
    trade_date: Mapped[str] = mapped_column(String(10), index=True, nullable=False, comment="交易日期")
    open: Mapped[float] = mapped_column(Numeric(12, 4), comment="开盘价")
    high: Mapped[float] = mapped_column(Numeric(12, 4), comment="最高价")
    low: Mapped[float] = mapped_column(Numeric(12, 4), comment="最低价")
    close: Mapped[float] = mapped_column(Numeric(12, 4), comment="收盘价")
    pre_close: Mapped[float] = mapped_column(Numeric(12, 4), default=0, comment="前收盘价")
    change: Mapped[float] = mapped_column(Numeric(12, 4), default=0, comment="涨跌额")
    pct_chg: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="涨跌幅（%）")
    vol: Mapped[float] = mapped_column(Numeric(20, 2), default=0, comment="成交量（手）")
    amount: Mapped[float] = mapped_column(Numeric(20, 2), default=0, comment="成交额（万元）")

    __mapper_args__ = {
        "primary_key": ["ts_code", "trade_date"],
    }


class DataSyncStatus(Base, TimestampMixin):
    """数据同步状态表，记录每次同步任务的执行状态"""
    __tablename__ = "data_sync_status"
    __table_args__ = {"comment": "数据同步状态表，记录每次同步任务的执行状态"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    sync_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False, comment="同步类型（stock_list/kline/financial等）")
    status: Mapped[str] = mapped_column(String(20), default="pending", comment="同步状态（pending/running/completed/failed）")
    last_sync_date: Mapped[str] = mapped_column(String(10), default="", comment="最后同步日期")
    total_count: Mapped[int] = mapped_column(Integer, default=0, comment="总记录数")
    success_count: Mapped[int] = mapped_column(Integer, default=0, comment="成功记录数")
    failed_count: Mapped[int] = mapped_column(Integer, default=0, comment="失败记录数")
    error_msg: Mapped[str] = mapped_column(Text, default="", comment="错误信息")
    started_at: Mapped[str] = mapped_column(String(20), default="", comment="同步开始时间")
    finished_at: Mapped[str] = mapped_column(String(20), default="", comment="同步结束时间")


class ConversationHistory(Base, TimestampMixin):
    """对话历史记录，存储用户与Agent的对话"""
    __tablename__ = "conversation_history"
    __table_args__ = {"comment": "对话历史记录，存储用户与Agent的对话"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    session_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False, comment="会话ID")
    user_id: Mapped[str] = mapped_column(String(128), default="default", index=True, comment="用户ID")
    user_message: Mapped[str] = mapped_column(Text, default="", comment="用户消息")
    assistant_message: Mapped[str] = mapped_column(Text, default="", comment="Agent回复")
    current_skill: Mapped[str] = mapped_column(String(50), default="", comment="当前技能/Worker名称")
    tool_calls = mapped_column(JSON, default=list, comment="工具调用记录（JSON）")
    step_count: Mapped[int] = mapped_column(Integer, default=0, comment="执行步数")
    response_time_ms: Mapped[int] = mapped_column(Integer, default=0, comment="响应耗时（毫秒）")
    status: Mapped[str] = mapped_column(String(20), default="completed", comment="状态（completed/failed/cancelled）")


class AgentAnalysisSession(Base, TimestampMixin):
    """多Agent分析会话，记录每次分析任务的完整信息"""
    __tablename__ = "agent_analysis_sessions"
    __table_args__ = {"comment": "多Agent分析会话，记录每次分析任务的完整信息"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    session_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False, comment="会话唯一ID")
    user_id: Mapped[str] = mapped_column(String(128), default="default", index=True, comment="用户ID")
    user_query: Mapped[str] = mapped_column(Text, default="", comment="用户原始问题")
    analysis_type: Mapped[str] = mapped_column(String(30), default="multi_agent", comment="分析类型（multi_agent/single_worker）")
    status: Mapped[str] = mapped_column(String(20), default="running", index=True, comment="会话状态（running/completed/failed）")

    selected_workers = mapped_column(JSON, default=list, comment="选中的Worker列表（JSON）")
    worker_count: Mapped[int] = mapped_column(Integer, default=0, comment="参与Worker数量")
    debate_enabled: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否启用辩论模式")
    debate_rounds: Mapped[int] = mapped_column(Integer, default=0, comment="辩论轮次")

    final_result: Mapped[str] = mapped_column(Text, default="", comment="最终分析结果")
    worker_results = mapped_column(JSON, default=dict, comment="各Worker结果汇总（JSON）")
    error_msg: Mapped[str] = mapped_column(Text, default="", comment="错误信息（如有）")

    total_duration_ms: Mapped[int] = mapped_column(Integer, default=0, comment="总耗时（毫秒）")
    total_steps: Mapped[int] = mapped_column(Integer, default=0, comment="总执行步数")


class AgentAuditLog(Base, TimestampMixin):
    """Agent执行审计日志，记录每个分析任务的详细执行步骤"""
    __tablename__ = "agent_audit_logs"
    __table_args__ = {"comment": "Agent执行审计日志，记录每个分析任务的详细执行步骤"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    session_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False, comment="关联会话ID")
    log_type: Mapped[str] = mapped_column(String(30), index=True, comment="日志类型（worker_start/worker_end/tool_call/analysis）")
    event_type: Mapped[str] = mapped_column(String(50), index=True, comment="事件类型（start/complete/error/timeout）")

    worker_name: Mapped[str] = mapped_column(String(64), default="", index=True, comment="Worker标识名")
    worker_display_name: Mapped[str] = mapped_column(String(100), default="", comment="Worker显示名称")
    worker_icon: Mapped[str] = mapped_column(String(20), default="", comment="Worker图标")
    worker_color: Mapped[str] = mapped_column(String(20), default="", comment="Worker颜色标识")

    content: Mapped[str] = mapped_column(Text, default="", comment="日志内容")
    content_preview: Mapped[str] = mapped_column(String(500), default="", comment="日志内容摘要")
    metadata_ = mapped_column("metadata", JSON, default=dict, comment="扩展元数据（JSON）")

    step_number: Mapped[int] = mapped_column(Integer, default=0, comment="步骤序号")
    round_number: Mapped[int] = mapped_column(Integer, default=0, comment="辩论轮次序号")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, comment="本步骤耗时（毫秒）")
    status: Mapped[str] = mapped_column(String(20), default="info", comment="日志状态（info/success/warning/error）")


class MoneyFlow(Base, TimestampMixin):
    """资金流向表，存储个股/板块的主力资金净流入数据"""
    __tablename__ = "money_flow"
    __table_args__ = {"comment": "资金流向表，存储个股/板块的主力资金净流入数据"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    ts_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False, comment="股票代码")
    trade_date: Mapped[str] = mapped_column(String(10), index=True, nullable=False, comment="交易日期")
    flow_type: Mapped[str] = mapped_column(String(20), default="stock", comment="资金流向类型（stock/industry）")

    main_net_inflow: Mapped[float] = mapped_column(Numeric(20, 2), default=0, comment="主力净流入（万元）")
    super_large_net_inflow: Mapped[float] = mapped_column(Numeric(20, 2), default=0, comment="超大单净流入（万元）")
    large_net_inflow: Mapped[float] = mapped_column(Numeric(20, 2), default=0, comment="大单净流入（万元）")
    medium_net_inflow: Mapped[float] = mapped_column(Numeric(20, 2), default=0, comment="中单净流入（万元）")
    small_net_inflow: Mapped[float] = mapped_column(Numeric(20, 2), default=0, comment="小单净流入（万元）")

    main_net_inflow_rate: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="主力净流入占比")
    super_large_net_inflow_rate: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="超大单净流入占比")
    large_net_inflow_rate: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="大单净流入占比")
    medium_net_inflow_rate: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="中单净流入占比")
    small_net_inflow_rate: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="小单净流入占比")

    __mapper_args__ = {"primary_key": ["ts_code", "trade_date", "flow_type"]}


class IndustryAggregation(Base, TimestampMixin):
    """行业聚合数据表，按行业汇总日度行情数据"""
    __tablename__ = "industry_aggregation"
    __table_args__ = {"comment": "行业聚合数据表，按行业汇总日度行情数据"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    industry: Mapped[str] = mapped_column(String(50), index=True, nullable=False, comment="行业名称")
    trade_date: Mapped[str] = mapped_column(String(10), index=True, nullable=False, comment="交易日期")

    stock_count: Mapped[int] = mapped_column(Integer, default=0, comment="行业内股票数量")
    avg_pct_chg: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="行业平均涨跌幅")
    median_pct_chg: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="行业中位数涨跌幅")
    up_count: Mapped[int] = mapped_column(Integer, default=0, comment="上涨家数")
    down_count: Mapped[int] = mapped_column(Integer, default=0, comment="下跌家数")
    total_volume: Mapped[float] = mapped_column(Numeric(20, 2), default=0, comment="行业总成交量")
    total_amount: Mapped[float] = mapped_column(Numeric(20, 2), default=0, comment="行业总成交额")
    avg_turnover_rate: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="行业平均换手率")

    __mapper_args__ = {"primary_key": ["industry", "trade_date"]}


class MacroData(Base, TimestampMixin):
    """宏观经济数据表，存储GDP、CPI、PMI等宏观指标"""
    __tablename__ = "macro_data"
    __table_args__ = {"comment": "宏观经济数据表，存储GDP、CPI、PMI等宏观指标"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    indicator: Mapped[str] = mapped_column(String(50), index=True, nullable=False, comment="宏观指标名称（如GDP、CPI、PMI）")
    period: Mapped[str] = mapped_column(String(10), index=True, nullable=False, comment="指标周期")
    value: Mapped[float] = mapped_column(Numeric(15, 4), default=0, comment="指标数值")
    unit: Mapped[str] = mapped_column(String(20), default="", comment="指标单位")
    source: Mapped[str] = mapped_column(String(50), default="akshare", comment="数据来源")

    __mapper_args__ = {"primary_key": ["indicator", "period"]}


class SentimentData(Base, TimestampMixin):
    """舆情/情绪数据表，存储新闻情绪、社交媒体热度等"""
    __tablename__ = "sentiment_data"
    __table_args__ = {"comment": "舆情/情绪数据表，存储新闻情绪、社交媒体热度等"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    ts_code: Mapped[str] = mapped_column(String(20), index=True, default="", comment="股票代码（空=全市场）")
    trade_date: Mapped[str] = mapped_column(String(10), index=True, nullable=False, comment="交易日期")
    sentiment_type: Mapped[str] = mapped_column(String(30), default="market", comment="舆情类型（market/stock/sector）")

    positive_count: Mapped[int] = mapped_column(Integer, default=0, comment="正面新闻数")
    negative_count: Mapped[int] = mapped_column(Integer, default=0, comment="负面新闻数")
    neutral_count: Mapped[int] = mapped_column(Integer, default=0, comment="中性新闻数")
    sentiment_score: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="情绪分数（-1到1）")
    heat_index: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="热度指数")

    __mapper_args__ = {"primary_key": ["ts_code", "trade_date", "sentiment_type"]}


class StockFactor(Base, TimestampMixin):
    """选股因子表，存储动量、反转、波动率等量化因子"""
    __tablename__ = "stock_factors"
    __table_args__ = {"comment": "选股因子表，存储动量、反转、波动率等量化因子"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    ts_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False, comment="股票代码")
    trade_date: Mapped[str] = mapped_column(String(10), index=True, nullable=False, comment="交易日期")

    momentum_5d: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="5日动量因子")
    momentum_20d: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="20日动量因子")
    momentum_60d: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="60日动量因子")
    reversal_5d: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="5日反转因子")
    volatility_20d: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="20日波动率")
    volume_ratio_5d: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="5日量比")
    turnover_avg_20d: Mapped[float] = mapped_column(Numeric(20, 2), default=0, comment="20日均成交额(万元)")
    amplitude_avg_20d: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="20日均振幅")
    rsi_14: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="14日RSI")
    composite_score: Mapped[float] = mapped_column(Numeric(10, 4), default=0, comment="综合评分")

    __mapper_args__ = {"primary_key": ["ts_code", "trade_date"]}


class AgentSkill(Base, TimestampMixin):
    """Agent 技能表，借鉴 Hermes skill_manage，PG 驱动存储"""
    __tablename__ = "agent_skills"
    __table_args__ = {"comment": "Agent 技能表，借鉴 Hermes skill_manage，PG 驱动存储"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False, comment="技能唯一名称")
    display_name: Mapped[str] = mapped_column(String(256), default="", comment="显示名称")
    category: Mapped[str] = mapped_column(String(64), default="general", index=True, comment="分类")
    description: Mapped[str] = mapped_column(Text, default="", comment="技能描述")
    trigger_keywords = mapped_column(JSON, default=list, comment="触发关键词列表")

    content: Mapped[str] = mapped_column(Text, default="", comment="完整的 SKILL.md 内容")
    metadata_ = mapped_column("metadata", JSON, default=dict, comment="结构化元数据")

    status: Mapped[str] = mapped_column(String(16), default="active", index=True, comment="状态: active/retired/deprecated")
    source: Mapped[str] = mapped_column(String(32), default="user_created", index=True, comment="来源: agent_created/hub_imported/preset/user_created")
    parent_name: Mapped[str] = mapped_column(String(128), nullable=True, index=True, comment="父技能（fork 来源）")

    use_count: Mapped[int] = mapped_column(Integer, default=0, comment="使用次数")
    success_count: Mapped[int] = mapped_column(Integer, default=0, comment="成功次数")
    fail_count: Mapped[int] = mapped_column(Integer, default=0, comment="失败次数")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="最后使用时间")
    last_patched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="最后修补时间")

    version: Mapped[int] = mapped_column(Integer, default=1, comment="版本号")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否置顶保护")
    created_by: Mapped[str] = mapped_column(String(64), default="user", comment="创建者")


class AgentMemory(Base, TimestampMixin):
    """Agent 三层记忆表，借鉴 Hermes MEMORY.md/USER.md，PG 驱动"""
    __tablename__ = "agent_memory"
    __table_args__ = {"comment": "Agent 三层记忆表：Frozen/Episodic/SkillRef"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    session_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False, comment="会话ID")
    user_id: Mapped[str] = mapped_column(String(128), default="default", index=True, comment="用户ID")

    layer: Mapped[str] = mapped_column(String(16), default="episodic", index=True, comment="记忆层级: frozen/episodic/skill_ref")
    content: Mapped[str] = mapped_column(Text, default="", comment="记忆内容")
    summary: Mapped[str] = mapped_column(Text, default="", comment="记忆摘要")
    tags = mapped_column(JSON, default=list, comment="标签列表")
    metadata_ = mapped_column("metadata", JSON, default=dict, comment="结构化元数据")

    skill_name: Mapped[str] = mapped_column(String(128), nullable=True, index=True, comment="关联技能名称")
    importance: Mapped[float] = mapped_column(Numeric(4, 3), default=0.5, comment="重要性权重 (0-1)")

    access_count: Mapped[int] = mapped_column(Integer, default=0, comment="访问次数")
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="最后访问时间")

    source: Mapped[str] = mapped_column(String(32), default="conversation", comment="来源")
    status: Mapped[str] = mapped_column(String(16), default="active", index=True, comment="状态: active/archived/consolidated")

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="过期时间")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="归档时间")


class AgentSession(Base, TimestampMixin):
    """Agent 会话记录表，存储每轮对话"""
    __tablename__ = "agent_sessions"
    __table_args__ = {"comment": "Agent 会话记录表，存储每轮对话"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键ID")
    session_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False, comment="会话ID")
    user_message: Mapped[str] = mapped_column(Text, default="", comment="用户消息")
    assistant_message: Mapped[str] = mapped_column(Text, default="", comment="Agent回复")
    tool_calls = mapped_column(JSON, default=list, comment="工具调用记录（JSON）")
    metadata_ = mapped_column("metadata", JSON, default=dict, comment="扩展元数据（JSON）")
