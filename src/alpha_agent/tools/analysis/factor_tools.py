"""选股因子工具"""
from typing import Optional
from langchain_core.tools import tool

from alpha_agent.utils.logger import logger


@tool
def get_stock_factors(
    ts_code: Optional[str] = None,
    trade_date: Optional[str] = None,
    top_n: int = 20,
) -> str:
    """获取选股因子数据，包含动量、波动率、换手率、RSI、综合评分等。

    使用场景：
    - 筛选强势股/弱势股
    - 多因子选股
    - 因子排名分析
    - 综合评分排序

    Args:
        ts_code: 股票代码（如'000001.SZ'），为空则返回top_n
        trade_date: 交易日期（YYYYMMDD），默认最新
        top_n: 返回排名前N只股票，默认20
    """
    try:
        from alpha_agent.infra.db.warehouse import get_data_warehouse

        wh = get_data_warehouse()
        if not wh.enabled:
            return "数据仓库不可用"

        if ts_code:
            df = wh.get_stock_factors(ts_code=ts_code, trade_date=trade_date)
            if df is None or df.empty:
                return f"未找到 {ts_code} 的因子数据"

            df = df.sort_values("trade_date", ascending=False)
            latest = df.iloc[0]
            lines = [f"股票因子: {ts_code} ({latest.get('trade_date', '')})", "", "=" * 60]
            lines.append(f"5日动量:     {latest.get('momentum_5d', 'N/A'):>10}%")
            lines.append(f"20日动量:    {latest.get('momentum_20d', 'N/A'):>10}%")
            lines.append(f"60日动量:    {latest.get('momentum_60d', 'N/A'):>10}%")
            lines.append(f"5日反转:     {latest.get('reversal_5d', 'N/A'):>10}%")
            lines.append(f"20日波动率:  {latest.get('volatility_20d', 'N/A'):>10}%")
            lines.append(f"5日量比:     {latest.get('volume_ratio_5d', 'N/A'):>10}")
            lines.append(f"20日均换手:  {latest.get('turnover_avg_20d', 'N/A'):>10}")
            lines.append(f"20日均振幅:  {latest.get('amplitude_avg_20d', 'N/A'):>10}%")
            lines.append(f"14日RSI:     {latest.get('rsi_14', 'N/A'):>10}")
            lines.append(f"综合评分:    {latest.get('composite_score', 'N/A'):>10}")
            return "\n".join(lines)

        df = wh.get_stock_factors(trade_date=trade_date)
        if df is None or df.empty:
            return "未找到因子数据"

        df = df.sort_values("composite_score", ascending=False)
        top = df.head(top_n)

        lines = [f"多因子综合评分 TOP {len(top)}：", "", "=" * 80]
        lines.append(f"{'排名':<6}{'代码':<14}{'20日动量':>10}{'60日动量':>10}{'RSI':>8}{'波动率':>10}{'综合评分':>10}")
        lines.append("-" * 80)

        for i, (_, row) in enumerate(top.iterrows(), 1):
            lines.append(
                f"{i:<6}{row['ts_code']:<14}"
                f"{row.get('momentum_20d', 0):>10.2f}%"
                f"{row.get('momentum_60d', 0):>10.2f}%"
                f"{row.get('rsi_14', 0):>8.1f}"
                f"{row.get('volatility_20d', 0):>10.2f}%"
                f"{row.get('composite_score', 0):>10.2f}"
            )

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"[get_stock_factors] 失败: {e}")
        return f"获取因子数据失败: {str(e)}"


def get_factor_tools() -> list:
    return [get_stock_factors]