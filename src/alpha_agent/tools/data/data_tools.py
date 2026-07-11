"""数据库 Schema 工具 —— get_database_schema。

借鉴 Hermes：LLM 直接写 SQL 通过 execute_code 执行，无需 text2sql 翻译层。
只保留 get_database_schema 让 LLM 了解表结构，SQL 由 LLM 自主生成。
"""
from __future__ import annotations
from typing import List

from langchain_core.tools import tool

from alpha_agent.infra.schema_provider import get_schema_text


@tool
def get_database_schema(force_refresh: bool = False) -> str:
    """获取数据仓库的完整表结构信息。

    当你不确定：
    - 有哪些表可以查询
    - 表里面有什么字段
    - 字段叫什么名字、什么类型

    就调用这个工具查看 Schema。Schema 信息会自动缓存 5 分钟。

    获取 Schema 后，使用 execute_code 编写 SQL 查询：
    ```python
    result = _execute_sql(\"\"\"
        SELECT trade_date, close FROM daily_kline
        WHERE ts_code = '600519.SH'
        ORDER BY trade_date DESC LIMIT 10
    \"\"\")
    print(result)
    ```

    Schema 从数据库系统表动态读取，新增表无需修改代码。

    Args:
        force_refresh: 是否强制刷新 Schema（默认 False，用缓存）
    """
    return get_schema_text(force_refresh=force_refresh)


def get_data_tools() -> List:
    """返回 data_tools 模块的所有工具函数"""
    return [get_database_schema]