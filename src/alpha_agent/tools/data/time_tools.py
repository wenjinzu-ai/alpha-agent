"""时间工具 —— 获取当前时间。

独立于 data_tools.py，遵循单一职责原则。
"""
from datetime import datetime
from langchain_core.tools import tool


@tool
def get_current_time() -> str:
    """获取当前时间和日期。

    当用户问"现在几点"、"今天几号"、"今天星期几"等时间相关问题时调用。
    返回当前的年、月、日、星期、时、分、秒。
    """
    now = datetime.now()
    weekday = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
    return f"""当前时间: {now.strftime('%Y年%m月%d日')} 星期{weekday} {now.strftime('%H:%M:%S')}
日期: {now.strftime('%Y-%m-%d')}
时间: {now.strftime('%H:%M:%S')}
星期: 星期{weekday}
年份: {now.year}
月份: {now.month}
日: {now.day}"""