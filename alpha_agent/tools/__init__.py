from alpha_agent.tools.market.stock_tools import get_all_tools as get_stock_tools
from alpha_agent.tools.analysis.backtest_tools import run_backtest, run_factor_backtest, run_universe_factor_backtest
from alpha_agent.tools.analysis.comparison_tools import compare_stocks
from alpha_agent.tools.market.news_tools import get_stock_news, get_stock_announcement
from alpha_agent.tools.market.monitor_tools import (
    get_realtime_quote,
    add_price_alert,
    list_alerts,
    check_alerts,
)
from alpha_agent.tools.portfolio.portfolio_tools import (
    create_portfolio,
    list_portfolios,
    add_position,
    remove_position,
    get_portfolio_summary,
    get_portfolio_risk,
    get_industry_distribution,
    get_rebalance_suggestion,
)
from alpha_agent.tools.analysis.screener_tools import (
    screen_stocks,
    screen_etfs,
    get_factor_ranking,
    get_industry_rotation,
    list_available_factors,
)
from alpha_agent.tools.data.data_tools import get_data_tools, get_database_schema
from alpha_agent.tools.data.time_tools import get_current_time
from alpha_agent.tools.data.web_tools import get_web_tools, web_search
from alpha_agent.tools.market.macro_tools import get_macro_tools, get_macro_data, get_money_flow, get_industry_aggregation
from alpha_agent.tools.analysis.factor_tools import get_factor_tools, get_stock_factors
from alpha_agent.tools.viz.chart_tools import get_chart_tools
from alpha_agent.tools.analysis.insight_tools import get_insight_tools
from alpha_agent.tools.analysis.attribution_tools import get_attribution_tools
from alpha_agent.tools.analysis.knowledge_graph_tools import get_knowledge_graph_tools

from alpha_agent.tools.core.terminal import terminal
from alpha_agent.tools.core.process import process
from alpha_agent.tools.core.execute_code import execute_code
from alpha_agent.tools.core.pipeline import execute_pipeline
from alpha_agent.tools.core.skill_manage import skill_manage
from alpha_agent.tools.core.delegate import delegate_task


def get_core_tools() -> list:
    tools = [
        terminal,
        process,
        execute_code,
        execute_pipeline,
        delegate_task,
        get_database_schema,
        get_current_time,
    ]

    tools.extend(get_web_tools())
    tools.extend(get_chart_tools())
    tools.extend(get_insight_tools())
    tools.extend(get_attribution_tools())

    return tools


def get_extended_tools() -> list:
    tools = [skill_manage]
    tools.extend(get_stock_tools())
    tools.append(run_backtest)
    tools.append(run_factor_backtest)
    tools.append(run_universe_factor_backtest)
    tools.append(compare_stocks)
    tools.append(get_stock_news)
    tools.append(get_stock_announcement)
    tools.append(get_realtime_quote)
    tools.append(add_price_alert)
    tools.append(list_alerts)
    tools.append(check_alerts)
    tools.append(create_portfolio)
    tools.append(list_portfolios)
    tools.append(add_position)
    tools.append(remove_position)
    tools.append(get_portfolio_summary)
    tools.append(get_portfolio_risk)
    tools.append(get_industry_distribution)
    tools.append(get_rebalance_suggestion)
    tools.append(screen_stocks)
    tools.append(screen_etfs)
    tools.append(get_factor_ranking)
    tools.append(get_industry_rotation)
    tools.append(list_available_factors)
    tools.extend(get_macro_tools())
    tools.extend(get_factor_tools())
    tools.extend(get_knowledge_graph_tools())
    return tools


def get_all_tools() -> list:
    tools = get_core_tools()
    tools.extend(get_extended_tools())
    return tools


def get_tools_map() -> dict:
    tools = get_all_tools()
    return {t.name: t for t in tools}


__all__ = [
    "get_core_tools",
    "get_extended_tools",
    "get_all_tools",
    "get_tools_map",
    "terminal",
    "process",
    "execute_code",
    "execute_pipeline",
    "get_stock_tools",
    "run_backtest",
    "run_factor_backtest",
    "run_universe_factor_backtest",
    "compare_stocks",
    "get_stock_news",
    "get_stock_announcement",
    "get_realtime_quote",
    "add_price_alert",
    "list_alerts",
    "check_alerts",
    "create_portfolio",
    "list_portfolios",
    "add_position",
    "remove_position",
    "get_portfolio_summary",
    "get_portfolio_risk",
    "get_industry_distribution",
    "get_rebalance_suggestion",
    "screen_stocks",
    "screen_etfs",
    "get_factor_ranking",
    "get_industry_rotation",
    "list_available_factors",
    "get_database_schema",
    "get_current_time",
    "web_search",
    "get_macro_data",
    "get_money_flow",
    "get_industry_aggregation",
    "get_stock_factors",
]