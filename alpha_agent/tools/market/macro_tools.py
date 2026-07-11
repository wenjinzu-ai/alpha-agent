"""宏观经济和资金流向工具"""
from typing import Optional
from langchain_core.tools import tool

from alpha_agent.utils.logger import logger


@tool
def get_macro_data(indicator: Optional[str] = None) -> str:
    """获取宏观经济数据，包括GDP、CPI、PMI、M2等。

    使用场景：
    - 宏观经济分析
    - 政策影响评估
    - 周期性判断
    - 大类资产配置

    Args:
        indicator: 指标名称（如'GDP同比'、'CPI同比'、'PMI'、'M2同比'），为空则返回全部
    """
    try:
        from alpha_agent.infra.db.warehouse import get_data_warehouse

        wh = get_data_warehouse()
        if not wh.enabled:
            return "数据仓库不可用"

        df = wh.get_macro_data(indicator=indicator)
        if df is None or df.empty:
            return "未找到宏观经济数据"

        lines = []
        if indicator:
            lines.append(f"宏观经济指标: {indicator}")
        else:
            lines.append("宏观经济数据总览")
        lines.append("=" * 60)

        for _, row in df.iterrows():
            lines.append(
                f"{row['indicator']:<20} "
                f"周期: {row['period']:<8} "
                f"数值: {row['value']:>10} {row.get('unit', '%')}"
            )

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"[get_macro_data] 失败: {e}")
        return f"获取宏观数据失败: {str(e)}"


@tool
def get_money_flow(
    ts_code: Optional[str] = None,
    trade_date: Optional[str] = None,
    top_n: int = 20,
) -> str:
    """获取资金流向数据，分析主力资金动向。

    使用场景：
    - 判断主力资金进出
    - 资金流向趋势分析
    - 个股资金面评估
    - 北向资金/主力资金监控

    Args:
        ts_code: 股票代码（如'000001.SZ'），为空则返回主力净流入top_n
        trade_date: 交易日期（YYYYMMDD），默认最新
        top_n: 返回排名前N只股票，默认20
    """
    try:
        from alpha_agent.infra.db.warehouse import get_data_warehouse

        wh = get_data_warehouse()
        if not wh.enabled:
            return "数据仓库不可用"

        if ts_code:
            df = wh.get_money_flow(ts_code=ts_code, trade_date=trade_date)
            if df is None or df.empty:
                return f"未找到 {ts_code} 的资金流向数据"

            latest = df.iloc[0]
            lines = [f"资金流向: {ts_code} ({latest.get('trade_date', '')})", "", "=" * 60]
            lines.append(f"主力净流入:    {latest.get('main_net_inflow', 0):>15,.2f}万")
            lines.append(f"  超大单净流入: {latest.get('super_large_net_inflow', 0):>15,.2f}万")
            lines.append(f"  大单净流入:   {latest.get('large_net_inflow', 0):>15,.2f}万")
            lines.append(f"  中单净流入:   {latest.get('medium_net_inflow', 0):>15,.2f}万")
            lines.append(f"  小单净流入:   {latest.get('small_net_inflow', 0):>15,.2f}万")
            lines.append(f"主力净流入占比: {latest.get('main_net_inflow_rate', 0):>15.2f}%")
            return "\n".join(lines)

        df = wh.get_money_flow(trade_date=trade_date)
        if df is None or df.empty:
            return "未找到资金流向数据"

        df = df.sort_values("main_net_inflow", ascending=False)
        top = df.head(top_n)

        lines = [f"主力资金净流入 TOP {len(top)}：", "", "=" * 70]
        lines.append(f"{'排名':<6}{'代码':<14}{'主力净流入':>15}{'超大单':>15}{'大单':>15}")
        lines.append("-" * 70)

        for i, (_, row) in enumerate(top.iterrows(), 1):
            lines.append(
                f"{i:<6}{row['ts_code']:<14}"
                f"{row.get('main_net_inflow', 0):>15,.0f}"
                f"{row.get('super_large_net_inflow', 0):>15,.0f}"
                f"{row.get('large_net_inflow', 0):>15,.0f}"
            )

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"[get_money_flow] 失败: {e}")
        return f"获取资金流向失败: {str(e)}"


@tool
def get_industry_aggregation(
    trade_date: Optional[str] = None,
    sort_by: str = "avg_pct_chg",
) -> str:
    """获取行业聚合数据，按行业汇总当日行情表现。

    使用场景：
    - 行业轮动分析
    - 板块强弱对比
    - 热点板块识别
    - 行业配置决策

    Args:
        trade_date: 交易日期（YYYYMMDD），默认最新
        sort_by: 排序字段（avg_pct_chg/up_count/stock_count/total_amount），默认涨跌幅
    """
    try:
        from alpha_agent.infra.db.warehouse import get_data_warehouse

        wh = get_data_warehouse()
        if not wh.enabled:
            return "数据仓库不可用"

        df = wh.get_industry_aggregation(trade_date=trade_date)
        if df is None or df.empty:
            return "未找到行业聚合数据"

        df = df.sort_values(sort_by, ascending=False)

        lines = [f"行业聚合数据 ({df.iloc[0].get('trade_date', '')})：", "", "=" * 90]
        lines.append(
            f"{'行业':<16}{'股票数':>8}{'均涨跌幅':>10}{'上涨':>8}{'下跌':>8}"
            f"{'总成交额(亿)':>14}"
        )
        lines.append("-" * 90)

        for _, row in df.iterrows():
            lines.append(
                f"{row['industry']:<16}"
                f"{row.get('stock_count', 0):>8}"
                f"{row.get('avg_pct_chg', 0):>10.2f}%"
                f"{row.get('up_count', 0):>8}"
                f"{row.get('down_count', 0):>8}"
                f"{row.get('total_amount', 0) / 1e8:>14.2f}"
            )

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"[get_industry_aggregation] 失败: {e}")
        return f"获取行业聚合失败: {str(e)}"


def get_macro_tools() -> list:
    return [get_macro_data, get_money_flow, get_industry_aggregation]