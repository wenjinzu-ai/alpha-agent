from typing import Optional, List, Dict, Any
from langchain_core.tools import tool
import pandas as pd

from alpha_agent.domain.market import get_data_service
from alpha_agent.utils.logger import logger


@tool
def get_stock_info(ts_code: str) -> str:
    """获取股票基本信息，包括名称、行业、市场、上市日期等。
    
    Args:
        ts_code: 股票代码，如 000001.SZ 或 600519.SH
    """
    try:
        ds = get_data_service()
        df = ds.get_stock_basic(ts_code=ts_code)
        if df is None or df.empty:
            return f"未找到股票 {ts_code} 的基本信息"
        row = df.iloc[0]
        lines = [
            f"股票代码: {row.get('ts_code', ts_code)}",
            f"股票名称: {row.get('name', '-')}",
            f"所属行业: {row.get('industry', '-')}",
            f"所在地区: {row.get('area', '-')}",
            f"上市日期: {row.get('list_date', '-')}",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"获取股票信息失败: {e}"


@tool
def get_kline_data(ts_code: str, period: str = "daily", adjust: str = "qfq", days: int = 120) -> str:
    """获取股票K线数据及简要技术指标概览。
    
    Args:
        ts_code: 股票代码，如 000001.SZ
        period: 周期，可选：daily（日线）、weekly（周线）、monthly（月线），默认daily
        adjust: 复权方式，可选：qfq（前复权）、hfq（后复权）、none（不复权），默认qfq
        days: 获取最近多少天的数据，默认120天
    """
    try:
        ds = get_data_service()
        df = ds.get_daily_kline(ts_code, period=period, adjust=adjust)
        if df is None or df.empty:
            return f"未找到 {ts_code} 的K线数据"

        df = df.tail(days)
        latest = df.iloc[-1]
        latest_date = latest.get("trade_date", "-")
        latest_close = float(latest.get("close", 0))

        closes = df["close"].astype(float).tolist()
        volumes = df["vol"].astype(float).tolist()

        ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else 0
        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else 0
        ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else 0

        highest = max(closes[-20:]) if len(closes) >= 20 else 0
        lowest = min(closes[-20:]) if len(closes) >= 20 else 0

        avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 0
        latest_vol = volumes[-1] if volumes else 0
        vol_ratio = latest_vol / avg_vol if avg_vol > 0 else 1

        lines = [
            f"股票: {ts_code}",
            f"最新交易日: {latest_date}",
            f"最新价: {latest_close:.3f}",
            f"20日最高: {highest:.3f}",
            f"20日最低: {lowest:.3f}",
            f"MA5: {ma5:.3f}",
            f"MA20: {ma20:.3f}",
            f"MA60: {ma60:.3f}",
            f"量比: {vol_ratio:.2f}",
            f"数据区间: {df.iloc[0].get('trade_date', '-')} ~ {latest_date} ({len(df)}条)",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"获取K线数据失败: {e}"


@tool
def get_financial_report(ts_code: str, report_type: str = "all") -> str:
    """获取股票财务报告数据，包括利润表、资产负债表关键指标。
    
    Args:
        ts_code: 股票代码，如 000001.SZ
        report_type: 报表类型，可选：income（利润表）、balance（资产负债表）、all（全部），默认all
    """
    try:
        ds = get_data_service()
        result_lines = [f"=== {ts_code} 财务报告 ==="]

        if report_type in ("income", "all"):
            df = ds.get_financial_report(ts_code, report_type="income")
            if df is not None and not df.empty:
                result_lines.append("\n--- 利润表（最近3期）---")
                for _, row in df.head(3).iterrows():
                    end_date = row.get("end_date", "-")
                    revenue = float(row.get("total_revenue", 0)) / 1e8
                    net_profit = float(row.get("net_profit", 0)) / 1e8
                    eps = float(row.get("eps", 0))
                    result_lines.append(
                        f"{end_date}: 营收{revenue:.2f}亿, 净利{net_profit:.2f}亿, EPS={eps:.3f}"
                    )

        if report_type in ("balance", "all"):
            df = ds.get_financial_report(ts_code, report_type="balance")
            if df is not None and not df.empty:
                result_lines.append("\n--- 资产负债表（最近2期）---")
                for _, row in df.head(2).iterrows():
                    end_date = row.get("end_date", "-")
                    result_lines.append(f"{end_date}: 数据已获取")

        if len(result_lines) == 1:
            return f"未找到 {ts_code} 的财务报告"
        return "\n".join(result_lines)
    except Exception as e:
        return f"获取财务报告失败: {e}"


@tool
def get_financial_indicators(ts_code: str) -> str:
    """获取股票财务指标，包括ROE、毛利率、净利率等关键指标。
    
    Args:
        ts_code: 股票代码，如 000001.SZ
    """
    try:
        ds = get_data_service()
        df = ds.get_financial_indicators(ts_code)
        if df is None or df.empty:
            return f"未找到 {ts_code} 的财务指标"

        latest = df.iloc[0]
        lines = [f"=== {ts_code} 财务指标（最新）==="]
        for col in df.columns[:15]:
            val = latest.get(col, "-")
            lines.append(f"  {col}: {val}")
        return "\n".join(lines)
    except Exception as e:
        return f"获取财务指标失败: {e}"


@tool
def run_full_analysis(ts_code: str) -> str:
    """对股票进行全面分析，包括基本面、技术面和风控三个维度，给出综合投资建议。
    当用户要求分析某只股票或询问投资建议时，使用此工具。
    
    Args:
        ts_code: 股票代码，如 000001.SZ
    """
    try:
        from alpha_agent.domain.comparison import get_stock_comparison

        cmp = get_stock_comparison()
        result = cmp._analyze_one(ts_code)
        if not result:
            return f"未找到 {ts_code} 的数据，无法进行分析"

        fund = result.get("fundamental", {})
        tech = result.get("technical", {})
        risk = result.get("risk_control", {})
        fund_detail = fund.get("detail", {})
        tech_detail = tech.get("detail", {})
        risk_detail = risk.get("detail", {})

        lines = [
            f"=== {ts_code} 全面分析结果 ===",
            f"股票名称: {result.get('name', '-')}",
            f"综合评级: {result.get('final_rating', '-')}",
            f"综合评分: {result.get('final_score', '-')}/100",
            "",
        ]

        lines.append("【基本面分析】")
        lines.append(f"  评级: {fund.get('rating', '-')} ({fund.get('score', '-')}分)")
        if "industry" in fund_detail:
            lines.append(f"  行业: {fund_detail['industry']}")
        if "industry_tier" in fund_detail:
            lines.append(f"  行业景气度: {fund_detail['industry_tier']}")
        if "list_years" in fund_detail:
            lines.append(f"  上市年限: {fund_detail['list_years']}年")
        if "maturity" in fund_detail:
            lines.append(f"  成熟期: {fund_detail['maturity']}")
        if "avg_amount_yi" in fund_detail:
            lines.append(f"  日均成交额: {fund_detail['avg_amount_yi']}亿")
        if "liquidity" in fund_detail:
            lines.append(f"  流动性: {fund_detail['liquidity']}")
        lines.append("")

        lines.append("【技术面分析】")
        lines.append(f"  评级: {tech.get('rating', '-')} ({tech.get('score', '-')}分)")
        if "current_price" in tech_detail:
            lines.append(f"  当前价: {tech_detail['current_price']}")
        if "trend" in tech_detail:
            lines.append(f"  趋势: {tech_detail['trend']}")
        if "ma5" in tech_detail:
            lines.append(f"  MA5/MA10/MA20: {tech_detail['ma5']}/{tech_detail['ma10']}/{tech_detail['ma20']}")
        if "momentum_10d" in tech_detail:
            lines.append(f"  10日涨跌幅: {tech_detail['momentum_10d']}%")
        lines.append("")

        lines.append("【风险评估】")
        lines.append(f"  评级: {risk.get('rating', '-')} ({risk.get('score', '-')}分)")
        if "volatility_20d_pct" in risk_detail:
            lines.append(f"  年化波动率: {risk_detail['volatility_20d_pct']}%")
        if "max_drawdown_60d_pct" in risk_detail:
            lines.append(f"  60日最大回撤: {risk_detail['max_drawdown_60d_pct']}%")
        if "avg_volume" in risk_detail:
            lines.append(f"  日均成交量: {risk_detail['avg_volume']:.0f}")
        if "liquidity" in risk_detail:
            lines.append(f"  流动性: {risk_detail['liquidity']}")
        if "position_pct" in risk_detail:
            lines.append(f"  建议仓位: {risk_detail['position_pct']}")
        lines.append("")

        lines.append("【综合建议】")
        if result.get("final_rating") in ["强烈推荐", "推荐"]:
            lines.append(f"  综合评分 {result.get('final_score')} 分，评级为{result.get('final_rating')}，")
            lines.append(f"  建议关注或逢低布局，仓位控制在 {risk_detail.get('position_pct', '合理范围')}。")
        elif result.get("final_rating") == "中性":
            lines.append(f"  综合评分 {result.get('final_score')} 分，评级为中性，")
            lines.append(f"  建议观望或轻仓试探，等待更明确的信号。")
        else:
            lines.append(f"  综合评分 {result.get('final_score')} 分，评级为{result.get('final_rating')}，")
            lines.append(f"  建议谨慎，控制仓位或回避。")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"全面分析失败: {e}")
        return f"全面分析失败: {e}"


def get_all_tools() -> list:
    return [
        get_stock_info,
        get_kline_data,
        get_financial_report,
        get_financial_indicators,
        run_full_analysis,
    ]


