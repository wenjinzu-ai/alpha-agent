"""知识图谱 —— 表关联与跨表推理。

核心能力：
1. 表关联路径发现：从 A 表到 B 表的最短 JOIN 路径
2. 跨表查询模板：常见跨表查询的 SQL 模板
3. 语义推理：从问题推断需要 JOIN 哪些表

设计原则：
- 轻量级，不依赖 Neo4j 等图数据库
- 基于 JSON 配置 + 简单图算法
- 可扩展：后续可升级为向量检索
"""
from __future__ import annotations
import json
import os
from collections import deque
from typing import List, Optional, Dict

from langchain_core.tools import tool

from alpha_agent.utils.logger import logger

_GRAPH_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "services", "knowledge_graph.json"
)


# 表关联图（边 = JOIN 关系）
EDGES = {
    ("daily_kline", "stocks"): {"join_key": "ts_code", "type": "1:1"},
    ("stocks", "money_flow"): {"join_key": "ts_code", "type": "1:N"},
    ("stocks", "financial_reports"): {"join_key": "ts_code", "type": "1:N"},
    ("stocks", "stock_factors"): {"join_key": "ts_code", "type": "1:N"},
    ("stocks", "sentiment_data"): {"join_key": "ts_code", "type": "1:N"},
    ("etf_daily_kline", "etfs"): {"join_key": "ts_code", "type": "1:1"},
    ("stocks", "industry_aggregation"): {"join_key": "industry", "type": "N:1"},
    ("daily_kline", "industry_aggregation"): {"join_key": "trade_date+industry", "type": "N:1"},
}

# 跨表查询模板
CROSS_TABLE_TEMPLATES = {
    "行业资金流向": {
        "tables": ["industry_aggregation", "stocks", "money_flow"],
        "sql_template": """
SELECT mf.trade_date, s.industry,
       SUM(CAST(mf.main_net_inflow AS FLOAT)) AS industry_main_flow,
       AVG(CAST(mf.main_net_inflow AS FLOAT)) AS avg_main_flow
FROM money_flow mf
JOIN stocks s ON mf.ts_code = s.ts_code
WHERE mf.trade_date = (SELECT MAX(trade_date) FROM money_flow)
GROUP BY s.industry, mf.trade_date
ORDER BY industry_main_flow DESC
        """.strip(),
        "description": "按行业汇总主力资金净流入"
    },
    "行业涨跌+成分股": {
        "tables": ["industry_aggregation", "stocks", "daily_kline"],
        "sql_template": """
SELECT s.industry, d.trade_date,
       COUNT(*) AS stock_count,
       AVG(CAST(d.pct_chg AS FLOAT)) AS avg_pct_chg,
       SUM(CASE WHEN d.pct_chg > 0 THEN 1 ELSE 0 END) AS up_count,
       SUM(CASE WHEN d.pct_chg < 0 THEN 1 ELSE 0 END) AS down_count
FROM daily_kline d
JOIN stocks s ON d.ts_code = s.ts_code
WHERE d.trade_date = (SELECT MAX(trade_date) FROM daily_kline)
GROUP BY s.industry, d.trade_date
ORDER BY avg_pct_chg DESC
        """.strip(),
        "description": "按行业统计涨跌分布"
    },
    "个股资金+行情": {
        "tables": ["daily_kline", "money_flow", "stocks"],
        "sql_template": """
SELECT d.ts_code, s.name, d.pct_chg, d.close,
       CAST(mf.main_net_inflow AS FLOAT) AS main_flow,
       CAST(mf.super_large_net_inflow AS FLOAT) AS super_large_flow
FROM daily_kline d
JOIN stocks s ON d.ts_code = s.ts_code
LEFT JOIN money_flow mf ON d.ts_code = mf.ts_code AND d.trade_date = mf.trade_date
WHERE d.trade_date = (SELECT MAX(trade_date) FROM daily_kline)
ORDER BY CAST(mf.main_net_inflow AS FLOAT) DESC
LIMIT 20
        """.strip(),
        "description": "个股行情+资金流向联合查询"
    },
    "因子+行情筛选": {
        "tables": ["stock_factors", "daily_kline", "stocks"],
        "sql_template": """
SELECT sf.ts_code, s.name, sf.composite_score,
       d.pct_chg, d.close, s.industry
FROM stock_factors sf
JOIN daily_kline d ON sf.ts_code = d.ts_code AND sf.trade_date = d.trade_date
JOIN stocks s ON sf.ts_code = s.ts_code
WHERE d.trade_date = (SELECT MAX(trade_date) FROM daily_kline)
  AND CAST(sf.composite_score AS FLOAT) > 0.7
ORDER BY CAST(sf.composite_score AS FLOAT) DESC
LIMIT 20
        """.strip(),
        "description": "按因子得分筛选优质股票"
    },
}


def _build_adjacency_list() -> Dict[str, List[str]]:
    """构建邻接表"""
    adj = {}
    for (a, b) in EDGES:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    return adj


def find_join_path(from_table: str, to_table: str) -> List[str]:
    """BFS 找最短 JOIN 路径"""
    adj = _build_adjacency_list()
    if from_table == to_table:
        return [from_table]

    visited = {from_table}
    queue = deque([(from_table, [from_table])])

    while queue:
        node, path = queue.popleft()
        for neighbor in adj.get(node, []):
            if neighbor == to_table:
                return path + [neighbor]
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))

    return []


def generate_join_sql(path: List[str]) -> str:
    """根据路径生成 JOIN SQL 片段"""
    if len(path) < 2:
        return ""

    parts = []
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        key = (a, b) if (a, b) in EDGES else (b, a)
        edge = EDGES.get(key, {})
        join_key = edge.get("join_key", "ts_code")

        if "+" in join_key:
            keys = join_key.split("+")
            on_clause = " AND ".join(f"{a}.{k} = {b}.{k}" for k in keys)
        else:
            on_clause = f"{a}.{join_key} = {b}.{join_key}"

        parts.append(f"JOIN {b} ON {on_clause}")

    return f"FROM {path[0]} " + " ".join(parts)


@tool
def find_cross_table_query(
    question: str = "",
) -> str:
    """跨表查询助手：根据问题推断需要 JOIN 哪些表，并生成 SQL 模板。

    当问题涉及多个表的数据时（如"行业资金流向"需要 industry + money_flow），
    调用此工具获取跨表 JOIN 路径和 SQL 模板。

    Args:
        question: 用户的问题
    """
    if not question:
        return "请提供问题"

    try:
        from alpha_agent.infra.schema_provider import TABLE_RELATIONS

        question_lower = question.lower()
        tables = []
        for table_name in TABLE_RELATIONS:
            clean_name = table_name.replace("_", " ")
            if clean_name in question_lower or table_name in question_lower:
                tables.append(table_name)

        if not tables:
            tables = ["daily_kline", "stocks"]

        if len(tables) <= 1:
            return f"此问题只涉及单表 ({tables[0] if tables else '未知'})，不需要跨表 JOIN"

        lines = [f"## 跨表查询分析\n"]
        lines.append(f"**推断涉及的表**: {', '.join(tables)}")

        # 查找 JOIN 路径
        if len(tables) >= 2:
            path = find_join_path(tables[0], tables[-1])
            if path:
                lines.append(f"\n**JOIN 路径**: {' → '.join(path)}")
                join_sql = generate_join_sql(path)
                if join_sql:
                    lines.append(f"\n**JOIN SQL 片段**:\n```sql\n{join_sql}\n```")
            else:
                lines.append(f"\n⚠️ 未找到 {tables[0]} 到 {tables[-1]} 的 JOIN 路径")

        # 匹配模板
        matched_template = None
        for name, tmpl in CROSS_TABLE_TEMPLATES.items():
            if all(t in tables for t in tmpl["tables"]):
                matched_template = (name, tmpl)
                break

        if matched_template:
            name, tmpl = matched_template
            lines.append(f"\n**匹配模板**: {name}")
            lines.append(f"**描述**: {tmpl['description']}")
            lines.append(f"\n```sql\n{tmpl['sql_template']}\n```")
        else:
            lines.append(f"\n💡 未匹配到预置模板，请基于 JOIN 路径自行构建 SQL")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"[knowledge_graph] 跨表查询失败: {e}")
        return f"跨表查询分析失败: {str(e)}"


@tool
def get_join_path(
    from_table: str = "",
    to_table: str = "",
) -> str:
    """查找两个表之间的 JOIN 路径。

    当你需要写跨表 SQL 但不确定如何 JOIN 时调用此工具。

    Args:
        from_table: 起始表名
        to_table: 目标表名
    """
    if not from_table or not to_table:
        return "请提供 from_table 和 to_table 参数"

    path = find_join_path(from_table, to_table)
    if not path:
        return f"未找到 {from_table} 到 {to_table} 的 JOIN 路径"

    lines = [f"## JOIN 路径: {from_table} → {to_table}\n"]
    lines.append(f"**路径**: {' → '.join(path)}")

    join_sql = generate_join_sql(path)
    if join_sql:
        lines.append(f"\n```sql\n{join_sql}\n```")

    # 列出每条边的关联信息
    lines.append(f"\n**关联详情**:")
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        key = (a, b) if (a, b) in EDGES else (b, a)
        edge = EDGES.get(key, {})
        lines.append(f"  - {a} ↔ {b}: 关联键={edge.get('join_key', '?')}, 类型={edge.get('type', '?')}")

    return "\n".join(lines)


def get_knowledge_graph_tools() -> list:
    return [find_cross_table_query, get_join_path]