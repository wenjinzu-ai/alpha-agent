"""Schema 提供者 —— 从 DataCatalog 动态获取表结构，零硬编码。

职责：
- 构建 LLM 可读的数据库 schema 文本
- 按需注入：只注入与问题相关的表，节省 Token
- 缓存 schema 文本（5分钟 TTL）
- 不做硬编码，完全依赖 DataCatalog 从 PG 系统表读取
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional, List

from alpha_agent.infra.catalog import DataCatalog
from alpha_agent.utils.logger import logger


_cached_schema: Optional[str] = None
_cached_schema_time: Optional[float] = None
SCHEMA_CACHE_TTL = 300

# 表关联映射：哪些表可以 JOIN
TABLE_RELATIONS = {
    "daily_kline": ["stocks"],
    "stocks": ["daily_kline", "money_flow", "financial_reports", "stock_factors"],
    "money_flow": ["stocks"],
    "financial_reports": ["stocks"],
    "stock_factors": ["stocks"],
    "industry_aggregation": [],
    "macro_data": [],
    "sentiment_data": ["stocks"],
    "etf_daily_kline": ["etfs"],
    "etfs": ["etf_daily_kline"],
}


def build_schema_text(tables: Optional[List[str]] = None) -> str:
    """从 DataCatalog 动态构建 schema 文本，零硬编码。

    Args:
        tables: 只包含这些表的 schema。为 None 则返回全量。
    """
    catalog = DataCatalog()
    all_tables = catalog.tables  # 使用已构建好的 tables

    if not all_tables:
        logger.warning("[schema_provider] DataCatalog 返回空，可能数据库连接失败")
        return "数据库连接失败，无法获取表结构"

    # 确定要包含的表
    if tables:
        # 按需注入：目标表 + 关联表
        expanded = set(tables)
        for t in tables:
            if t in TABLE_RELATIONS:
                expanded.update(TABLE_RELATIONS[t])
        # 确保表存在
        target_tables = {k: v for k, v in all_tables.items() if k in expanded}
    else:
        target_tables = all_tables

    lines = []
    lines.append("数据仓库表结构（从数据库动态发现）：")
    lines.append("=" * 50)

    for table_name, table_info in target_tables.items():
        lines.append("")
        lines.append(f"表名: {table_name}")
        if table_info.description:
            lines.append(f"说明: {table_info.description}")
        lines.append("字段:")
        for col in table_info.columns:
            pk = " [主键]" if col.is_pk else ""
            comment = f" - {col.comment}" if col.comment else ""
            lines.append(f"  - {col.name}: {col.type}{pk}{comment}")
        lines.append("-" * 30)

    # JOIN 提示
    if tables:
        lines.append("")
        lines.append("表关联关系：")
        for t in tables:
            if t in TABLE_RELATIONS and TABLE_RELATIONS[t]:
                related = TABLE_RELATIONS[t]
                lines.append(f"  - {t} ↔ {', '.join(related)} (通过 ts_code 关联)")

    lines.append("")
    lines.append("使用示例：")
    lines.append("  - SELECT COUNT(*) FROM stocks")
    lines.append("  - SELECT industry, COUNT(*) FROM stocks GROUP BY industry ORDER BY 2 DESC")
    lines.append("  - SELECT trade_date, close, pct_chg FROM daily_kline WHERE ts_code='000001.SZ' ORDER BY trade_date DESC LIMIT 10")
    lines.append("")
    lines.append("注意事项：")
    lines.append("  - 只允许 SELECT 查询")
    lines.append("  - 日期格式: YYYYMMDD 字符串（如 '20250101'）")
    lines.append("  - ts_code 格式: 代码.市场（如 '000001.SZ', '600519.SH'）")

    return "\n".join(lines)


def get_schema_text(
    force_refresh: bool = False,
    tables: Optional[List[str]] = None,
) -> str:
    """获取 schema 文本，带缓存。

    Args:
        force_refresh: 是否强制刷新缓存
        tables: 只包含这些表的 schema（按需注入，节省 Token）
    """
    global _cached_schema, _cached_schema_time

    # 按需注入不走缓存
    if tables:
        text = build_schema_text(tables)
        logger.info(f"[schema_provider] 按需 Schema 构建完成，表: {tables}，{len(text)} 字符")
        return text

    now = datetime.now().timestamp()
    if not force_refresh and _cached_schema and _cached_schema_time:
        if (now - _cached_schema_time) < SCHEMA_CACHE_TTL:
            return _cached_schema

    text = build_schema_text()
    _cached_schema = text
    _cached_schema_time = now

    logger.info(f"[schema_provider] Schema 构建完成，{len(text)} 字符")
    return text