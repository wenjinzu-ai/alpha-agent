from typing import List
from langchain_core.tools import tool

from alpha_agent.domain.comparison import get_stock_comparison
from alpha_agent.utils.logger import logger


@tool
def compare_stocks(ts_codes: List[str]) -> str:
    """对比多只股票，进行横向比较，给出排名和各维度评分对比。
    当用户询问"哪个好"、"对比一下"、"选哪个"等问题时使用。
    
    Args:
        ts_codes: 股票代码列表，如 ["000001.SZ", "600519.SH", "300750.SZ"]
    """
    try:
        comp = get_stock_comparison()
        result = comp.compare(ts_codes)
        return comp.format_comparison_text(result)
    except Exception as e:
        logger.error(f"股票对比失败: {e}")
        return f"对比失败: {e}"
