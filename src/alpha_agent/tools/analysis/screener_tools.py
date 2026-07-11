from langchain_core.tools import tool
from typing import Optional, List

from alpha_agent.utils.logger import logger
from alpha_agent.domain.screener import get_stock_screener
from alpha_agent.domain.factor import get_factor_service
from alpha_agent.domain.rotation import get_industry_rotation_service


@tool
def screen_stocks(
    universe: str = "stock",
    top_n: int = 20,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    industries: Optional[List[str]] = None,
) -> str:
    """全市场股票/ETF选股扫描，根据技术面、动量、价值三维度综合评分排名。

    Args:
        universe: 扫描范围，'stock'为A股股票，'etf'为ETF
        top_n: 返回前N名，默认20
        min_price: 最低价格过滤
        max_price: 最高价格过滤
        industries: 指定行业列表，仅股票有效
    """
    try:
        screener = get_stock_screener()
        results = screener.scan(
            universe=universe,
            top_n=top_n,
            min_price=min_price,
            max_price=max_price,
            industries=industries,
        )
        if not results:
            return "未找到符合条件的标的，请检查数据是否已同步。"
        return screener.get_scan_report(results, top_n=top_n)
    except Exception as e:
        logger.error(f"选股扫描失败: {e}")
        return f"扫描失败: {e}"


@tool
def get_factor_ranking(
    factor_name: str = "change_pct_20d",
    universe: str = "stock",
    top_n: int = 20,
    ascending: bool = False,
) -> str:
    """按单个因子对全市场股票/ETF进行排名。

    可用因子: ma5, ma10, ma20, ma60, ma120, ma250,
              macd_dif, macd_dea, macd_bar,
              rsi_6, rsi_14, rsi_24,
              kdj_k, kdj_d, kdj_j,
              vol_ratio, change_pct_1d, change_pct_5d, change_pct_20d, change_pct_60d,
              position_20d, volatility_60d, latest_close

    Args:
        factor_name: 因子名称
        universe: 'stock'或'etf'
        top_n: 返回前N名
        ascending: 是否升序排列（默认降序，从高到低）
    """
    try:
        svc = get_factor_service()
        df = svc.rank_by_factor(factor_name, universe=universe, top_n=top_n, ascending=ascending)
        if df.empty:
            return f"未找到数据，请检查数据是否已同步，或因子名称是否正确。可用因子: {', '.join(svc.get_available_factors().keys())}"

        lines = [
            f"📊 因子排名: {factor_name}",
            f"范围: {universe}, 数量: {len(df)}",
            f"排序: {'升序' if ascending else '降序'}",
            "",
            f"{'排名':<5}{'代码':<12}{'名称':<10}{factor_name:<15}",
            "-" * 50,
        ]
        for i, row in df.iterrows():
            val = row[factor_name]
            val_str = f"{val:.2f}" if isinstance(val, float) else str(val)
            lines.append(f"{i+1:<5}{row['ts_code']:<12}{row['name']:<10}{val_str:<15}")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"因子排名失败: {e}")
        return f"查询失败: {e}"


@tool
def get_industry_rotation(top_n: int = 5) -> str:
    """行业轮动分析，找出当前最强和最弱的行业。

    Args:
        top_n: 最强/最弱各展示N个行业，默认5
    """
    try:
        svc = get_industry_rotation_service()
        signals = svc.get_rotation_signals(top_n=top_n)
        if not signals:
            return "暂无行业轮动数据，请先同步股票数据。"
        return svc.get_report(signals)
    except Exception as e:
        logger.error(f"行业轮动分析失败: {e}")
        return f"分析失败: {e}"


@tool
def list_available_factors() -> str:
    """列出所有可用的技术因子名称和说明。"""
    try:
        svc = get_factor_service()
        factors = svc.get_available_factors()
        lines = ["📋 可用技术因子列表:", ""]
        for name, desc in factors.items():
            lines.append(f"  {name:<20} - {desc}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"获取因子列表失败: {e}")
        return f"查询失败: {e}"
