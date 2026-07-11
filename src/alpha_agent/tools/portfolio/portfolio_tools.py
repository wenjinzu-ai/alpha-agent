from typing import Optional, List
from langchain_core.tools import tool

from alpha_agent.domain.portfolio import get_portfolio_service
from alpha_agent.utils.logger import logger


@tool
def create_portfolio(name: str, description: str = "", initial_capital: float = 100000.0) -> str:
    """创建一个新的投资组合。
    
    Args:
        name: 组合名称
        description: 组合描述
        initial_capital: 初始资金，默认10万
    """
    try:
        svc = get_portfolio_service()
        pf_id = svc.create_portfolio(name, description, initial_capital)
        return f"✅ 组合创建成功\n组合ID: {pf_id}\n名称: {name}\n初始资金: {initial_capital:,.2f}"
    except Exception as e:
        logger.error(f"创建组合失败: {e}")
        return f"创建失败: {e}"


@tool
def list_portfolios() -> str:
    """查看所有投资组合列表。"""
    try:
        svc = get_portfolio_service()
        pfs = svc.list_portfolios()
        if not pfs:
            return "暂无组合，使用 create_portfolio 创建一个"

        lines = ["=== 我的组合 ==="]
        for i, p in enumerate(pfs, 1):
            lines.append(
                f"{i}. {p['name']} (ID: {p['portfolio_id']})"
                f"  - {p['position_count']}只持仓"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"查询组合列表失败: {e}")
        return f"查询失败: {e}"


@tool
def add_position(portfolio_id: str, ts_code: str, shares: int, cost_price: float) -> str:
    """向组合中添加股票持仓（买入）。
    
    Args:
        portfolio_id: 组合ID
        ts_code: 股票代码，如 000001.SZ
        shares: 买入股数
        cost_price: 买入成本价
    """
    try:
        svc = get_portfolio_service()
        ok = svc.add_position(portfolio_id, ts_code, shares, cost_price)
        if ok:
            return f"✅ 已添加持仓: {ts_code} {shares}股 @ {cost_price}"
        return "❌ 添加失败，组合不存在"
    except Exception as e:
        logger.error(f"添加持仓失败: {e}")
        return f"添加失败: {e}"


@tool
def remove_position(portfolio_id: str, ts_code: str, shares: Optional[int] = None) -> str:
    """从组合中移除股票持仓（卖出）。
    
    Args:
        portfolio_id: 组合ID
        ts_code: 股票代码
        shares: 卖出股数，不填则清仓
    """
    try:
        svc = get_portfolio_service()
        ok = svc.remove_position(portfolio_id, ts_code, shares)
        if ok:
            action = f"减仓{shares}股" if shares else "清仓"
            return f"✅ 已{action}: {ts_code}"
        return "❌ 移除失败"
    except Exception as e:
        logger.error(f"移除持仓失败: {e}")
        return f"移除失败: {e}"


@tool
def get_portfolio_summary(portfolio_id: str) -> str:
    """获取投资组合的整体概览，包括总市值、总收益、持仓数量、集中度等。
    
    Args:
        portfolio_id: 组合ID
    """
    try:
        svc = get_portfolio_service()
        summary = svc.get_summary(portfolio_id)
        if not summary:
            return "组合不存在"

        positions = svc.get_positions(portfolio_id)

        lines = [
            f"=== {summary.name} 组合概览 ===",
            f"总市值: {summary.total_market_value:,.2f} 元",
            f"总成本: {summary.total_cost:,.2f} 元",
            f"总收益: {summary.total_profit:,.2f} 元 ({summary.total_profit_pct:+.2f}%)",
            f"初始资金: {summary.initial_capital:,.2f} 元",
            f"持仓数量: {summary.position_count} 只",
            f"行业数量: {summary.industry_count} 个",
            f"前3大持仓集中度: {summary.concentration_ratio:.2f}%",
        ]

        if positions:
            lines.append("")
            lines.append("--- 持仓明细 ---")
            for i, p in enumerate(positions, 1):
                profit_str = f"{p.profit:+,.0f} ({p.profit_pct:+.2f}%)"
                lines.append(
                    f"{i}. {p.ts_code} {p.stock_name} | "
                    f"{p.shares}股 | 市值{p.market_value:,.0f} | "
                    f"占比{p.weight*100:.1f}% | "
                    f"盈亏{profit_str}"
                )

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"获取组合概览失败: {e}")
        return f"查询失败: {e}"


@tool
def get_portfolio_risk(portfolio_id: str) -> str:
    """分析投资组合的风险指标，包括波动率、最大回撤、夏普比率、VaR等。
    
    Args:
        portfolio_id: 组合ID
    """
    try:
        svc = get_portfolio_service()
        risk = svc.analyze_risk(portfolio_id)

        lines = [
            f"=== 组合风险分析 ===",
            f"20日波动率(年化): {risk.volatility_20d:.2f}%",
            f"60日波动率(年化): {risk.volatility_60d:.2f}%",
            f"最大回撤: {risk.max_drawdown:.2f}%",
            f"夏普比率: {risk.sharpe_ratio:.2f}",
            f"95% VaR(日): {risk.var_95:.2f}%",
        ]

        lines.append("")
        if risk.volatility_20d < 15:
            vol_level = "低"
        elif risk.volatility_20d < 25:
            vol_level = "中"
        else:
            vol_level = "高"
        lines.append(f"风险等级: {vol_level}波动")

        if risk.sharpe_ratio > 1.5:
            lines.append("风险收益比: 优秀")
        elif risk.sharpe_ratio > 1.0:
            lines.append("风险收益比: 良好")
        elif risk.sharpe_ratio > 0.5:
            lines.append("风险收益比: 一般")
        else:
            lines.append("风险收益比: 较差")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"风险分析失败: {e}")
        return f"分析失败: {e}"


@tool
def get_industry_distribution(portfolio_id: str) -> str:
    """查看投资组合的行业分布，评估分散化程度。
    
    Args:
        portfolio_id: 组合ID
    """
    try:
        svc = get_portfolio_service()
        dist = svc.get_industry_distribution(portfolio_id)
        if not dist:
            return "暂无行业分布数据"

        lines = ["=== 行业分布 ==="]
        for i, (ind, pct) in enumerate(dist.items(), 1):
            bar = "█" * int(pct / 5)
            lines.append(f"{i}. {ind:<10} {pct:5.1f}% {bar}")

        n_industries = len(dist)
        lines.append("")
        if n_industries >= 8:
            lines.append("分散化程度: 优秀")
        elif n_industries >= 5:
            lines.append("分散化程度: 良好")
        elif n_industries >= 3:
            lines.append("分散化程度: 一般")
        else:
            lines.append("分散化程度: 较差，建议增加行业配置")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"获取行业分布失败: {e}")
        return f"查询失败: {e}"


@tool
def get_rebalance_suggestion(portfolio_id: str) -> str:
    """获取组合再平衡建议，包括仓位调整、分散化建议等。
    
    Args:
        portfolio_id: 组合ID
    """
    try:
        svc = get_portfolio_service()
        suggestions = svc.suggest_rebalance(portfolio_id)
        if not suggestions:
            return "组合配置合理，暂无调整建议"

        lines = ["=== 再平衡建议 ==="]
        for i, s in enumerate(suggestions, 1):
            action_map = {
                "reduce": "⚠️ 减仓",
                "diversify": "💡 分散",
                "review": "🔍 评估",
            }
            action = action_map.get(s["action"], s["action"])
            code = s["ts_code"] or ""
            name = s["stock_name"] or ""
            lines.append(f"{i}. {action} {code} {name}")
            lines.append(f"   原因: {s['reason']}")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"获取再平衡建议失败: {e}")
        return f"获取建议失败: {e}"
