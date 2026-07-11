from langchain_core.tools import tool

from alpha_agent.domain.market import get_data_service
from alpha_agent.utils.logger import logger


@tool
def get_stock_news(ts_code: str, limit: int = 10) -> str:
    """获取股票相关的最新新闻资讯。
    当用户询问新闻、消息、最新动态、最近有什么事等问题时使用。
    
    Args:
        ts_code: 股票代码，如 000001.SZ
        limit: 返回新闻条数，默认10条
    """
    try:
        ds = get_data_service()
        df = ds.get_stock_news(ts_code, limit=limit)
        if df is None or df.empty:
            return f"暂无 {ts_code} 的相关新闻"

        lines = [f"=== {ts_code} 最新新闻 ==="]
        for i, (_, row) in enumerate(df.iterrows(), 1):
            title = row.get("标题", row.get("title", "-"))
            pub_time = row.get("发布时间", row.get("date", row.get("pub_time", "-")))
            source = row.get("来源", row.get("source", ""))
            line = f"{i}. [{pub_time}] {title}"
            if source:
                line += f"（{source}）"
            lines.append(line)

        lines.append("")
        lines.append(f"共 {len(df)} 条新闻")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"获取新闻失败: {e}")
        return f"获取新闻失败: {e}"


@tool
def get_stock_announcement(ts_code: str, limit: int = 10) -> str:
    """获取股票发布的公告信息。
    当用户询问公告、公司公告、最新公告等问题时使用。
    
    Args:
        ts_code: 股票代码，如 000001.SZ
        limit: 返回公告条数，默认10条
    """
    try:
        ds = get_data_service()
        df = ds.get_stock_announcement(ts_code, limit=limit)
        if df is None or df.empty:
            return f"暂无 {ts_code} 的公告"

        lines = [f"=== {ts_code} 最新公告 ==="]
        for i, (_, row) in enumerate(df.iterrows(), 1):
            title = row.get("公告标题", row.get("title", row.get("公告名称", "-")))
            pub_time = row.get("公告日期", row.get("date", row.get("pub_date", "-")))
            ann_type = row.get("公告类型", row.get("type", ""))
            line = f"{i}. [{pub_time}] {title}"
            if ann_type:
                line += f"（{ann_type}）"
            lines.append(line)

        lines.append("")
        lines.append(f"共 {len(df)} 条公告")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"获取公告失败: {e}")
        return f"获取公告失败: {e}"
