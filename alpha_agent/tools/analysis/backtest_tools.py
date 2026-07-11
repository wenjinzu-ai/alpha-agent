from typing import List, Optional
from langchain_core.tools import tool

from alpha_agent.domain.market import get_data_service
from alpha_agent.domain.quant import BacktestEngine
from alpha_agent.domain.backtest import get_factor_backtest_engine
from alpha_agent.infra.db.warehouse import get_data_warehouse
from alpha_agent.utils.logger import logger


@tool
def run_backtest(ts_code: str, days: int = 500, initial_capital: float = 100000.0) -> str:
    """对单只股票进行历史回测，验证技术指标策略的历史表现。
    返回收益率、夏普比率、最大回撤、胜率等关键绩效指标。
    
    Args:
        ts_code: 股票代码，如 000001.SZ
        days: 回测天数，默认500天（约2年）
        initial_capital: 初始资金，默认10万
    """
    try:
        ds = get_data_service()
        df = ds.get_daily_kline(ts_code, adjust="qfq")
        if df is None or len(df) < 60:
            return f"股票 {ts_code} 的K线数据不足，无法回测"

        df = df.tail(days).reset_index(drop=True)

        engine = BacktestEngine(initial_capital=initial_capital)
        result = engine.run(ts_code=ts_code, kline_df=df)

        s = result.summary()
        lines = [
            f"=== {ts_code} 策略回测报告 ===",
            f"回测区间: {s['period']}",
            f"初始资金: {s['初始资金']}",
            f"最终资金: {s['最终资金']}",
            "",
            "--- 收益表现 ---",
            f"总收益率: {s['总收益率']}",
            f"年化收益率: {s['年化收益率']}",
            f"基准收益率: {s['基准收益率']}",
            f"超额收益率: {s['超额收益率']}",
            "",
            "--- 风险指标 ---",
            f"最大回撤: {s['最大回撤']}",
            f"夏普比率: {s['夏普比率']}",
            f"索提诺比率: {s['索提诺比率']}",
            "",
            "--- 交易统计 ---",
            f"总交易次数: {s['总交易次数']}",
            f"胜率: {s['胜率']}",
            f"盈亏比: {s['盈亏比']}",
            f"盈利次数: {s['盈利次数']}",
            f"亏损次数: {s['亏损次数']}",
            f"最大连盈: {s['最大连盈']}次",
            f"最大连亏: {s['最大连亏']}次",
        ]

        if result.trades:
            lines.append("")
            lines.append("--- 最近5笔交易 ---")
            for t in result.trades[-5:]:
                pnl_str = f"+{t.pnl:.2f}" if t.pnl >= 0 else f"{t.pnl:.2f}"
                pct_str = f"+{t.pnl_pct:.2f}%" if t.pnl_pct >= 0 else f"{t.pnl_pct:.2f}%"
                lines.append(
                    f"  {t.open_date}~{t.close_date}: "
                    f"开仓价{t.open_price:.2f} → "
                    f"平仓价{t.close_price:.2f} | "
                    f"{pnl_str} ({pct_str})"
                )

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"回测失败: {e}")
        return f"回测失败: {e}"


@tool
def run_factor_backtest(
    ts_codes: List[str],
    factor_name: str = "technical_score",
    rebalance_freq: str = "monthly",
    top_n: int = 10,
    initial_capital: float = 100000.0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """因子选股策略回测，基于因子评分定期调仓，验证多股票组合策略表现。

    可用因子: technical_score(技术面综合分), momentum_score(动量分), value_score(价值分),
              ma5, ma10, ma20, ma60, rsi_14, change_pct_20d, volatility_60d 等

    调仓频率: daily(每日), weekly(每周), monthly(每月), quarterly(每季)

    Args:
        ts_codes: 股票代码列表，如 ["000001.SZ", "600519.SH"]
        factor_name: 用于选股的因子名称，默认 technical_score
        rebalance_freq: 调仓频率，默认 monthly
        top_n: 每期持有因子排名前N只股票，默认10
        initial_capital: 初始资金，默认10万
        start_date: 回测开始日期，如 20230101（可选）
        end_date: 回测结束日期，如 20241231（可选）
    """
    try:
        if not ts_codes:
            return "请提供至少一只股票代码"

        engine = get_factor_backtest_engine()
        engine.initial_capital = initial_capital

        result = engine.run_factor_strategy(
            universe=ts_codes,
            factor_name=factor_name,
            rebalance_freq=rebalance_freq,
            top_n=min(top_n, len(ts_codes)),
            start_date=start_date,
            end_date=end_date,
        )

        return engine.get_report(result)
    except Exception as e:
        logger.error(f"因子回测失败: {e}")
        return f"因子回测失败: {e}"


@tool
def run_universe_factor_backtest(
    universe: str = "stock",
    factor_name: str = "technical_score",
    rebalance_freq: str = "monthly",
    top_n: int = 10,
    initial_capital: float = 100000.0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """全市场因子选股策略回测，从全市场股票/ETF中按因子选股并定期调仓。

    注意：需要先同步股票/ETF列表和K线数据到本地数据仓库。

    Args:
        universe: 选股范围，'stock'为A股，'etf'为ETF，默认 stock
        factor_name: 用于选股的因子名称，默认 technical_score
        rebalance_freq: 调仓频率，默认 monthly
        top_n: 每期持有因子排名前N只，默认10
        initial_capital: 初始资金，默认10万
        start_date: 回测开始日期（可选）
        end_date: 回测结束日期（可选）
    """
    try:
        warehouse = get_data_warehouse()
        if not warehouse.enabled:
            return "本地数据仓库未启用，无法进行全市场回测。请先配置PostgreSQL数据库。"

        if universe == "stock":
            stock_df = warehouse.get_stock_list()
        elif universe == "etf":
            stock_df = warehouse.get_etf_list()
        else:
            return f"不支持的universe: {universe}，请使用 'stock' 或 'etf'"

        if stock_df.empty:
            return f"{universe} 列表为空，请先同步数据。"

        ts_codes = stock_df["ts_code"].head(100).tolist()

        engine = get_factor_backtest_engine()
        engine.initial_capital = initial_capital

        result = engine.run_factor_strategy(
            universe=ts_codes,
            factor_name=factor_name,
            rebalance_freq=rebalance_freq,
            top_n=top_n,
            start_date=start_date,
            end_date=end_date,
        )

        lines = [
            f"📊 全市场因子回测（{universe}）",
            f"样本数: {len(ts_codes)} 只, 因子: {factor_name}",
            f"调仓频率: {rebalance_freq}, 持仓数: {top_n}",
            "=" * 50,
        ]
        lines.append(engine.get_report(result))
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"全市场因子回测失败: {e}")
        return f"全市场因子回测失败: {e}"

