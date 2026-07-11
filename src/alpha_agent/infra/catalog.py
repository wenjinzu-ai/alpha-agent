"""数据目录服务 —— 构建数据地图，让 Agent 对数据了如指掌。

业界做法：Databricks Unity Catalog / Snowflake Catalog
核心思路：从数据库系统表（pg_class/pg_description）动态读取表和字段注释，零硬编码。
新增表、调整表结构 → 只要数据库有注释，Agent 自动感知。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import text

from alpha_agent.infra.db.database import SessionLocal, engine
from alpha_agent.utils.logger import logger


@dataclass
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    comment: str = ""
    is_pk: bool = False


@dataclass
class TableInfo:
    name: str
    description: str
    row_count: int = 0
    date_min: Optional[str] = None
    date_max: Optional[str] = None
    columns: list[ColumnInfo] = field(default_factory=list)
    key_columns: list[str] = field(default_factory=list)
    data_freshness: str = "unknown"


def _parse_freshness(date_max: Optional[str]) -> str:
    """根据最新日期判断数据新鲜度"""
    if not date_max:
        return "unknown"
    try:
        s = str(date_max)
        if len(s) == 8:
            latest_dt = datetime.strptime(s, "%Y%m%d")
        elif len(s) >= 10:
            latest_dt = datetime.strptime(s[:10], "%Y-%m-%d")
        else:
            return "unknown"
        days_ago = (datetime.now() - latest_dt).days
        if days_ago <= 1:
            return "🟢 实时"
        elif days_ago <= 3:
            return "🟡 较新"
        elif days_ago <= 7:
            return "🟠 稍旧"
        else:
            return f"🔴 {days_ago}天前"
    except Exception:
        return "unknown"


class DataCatalog:
    """数据目录 —— 通过查询数据库系统表动态构建，零硬编码。

    读取来源：
    - obj_description() → 表注释（COMMENT ON TABLE）
    - col_description() → 列注释（COMMENT ON COLUMN）
    - pg_class / pg_attribute → 表结构元数据
    - COUNT(*) → 行数
    - MIN/MAX → 日期范围
    """

    def __init__(self):
        self.tables: dict[str, TableInfo] = {}
        self.total_rows: int = 0
        self.total_tables: int = 0
        self.latest_trade_date: Optional[str] = None
        self.earliest_trade_date: Optional[str] = None
        self.build()

    def build(self):
        """扫描数据库，构建数据地图"""
        logger.info("[DataCatalog] 开始构建数据地图...")
        try:
            self._build_from_pg()
            logger.info(
                f"[DataCatalog] 数据地图构建完成: "
                f"{self.total_tables} 张表, {self.total_rows:,} 条数据, "
                f"K线范围: {self.earliest_trade_date} ~ {self.latest_trade_date}"
            )
        except Exception as e:
            logger.error(f"[DataCatalog] 数据地图构建失败: {e}", exc_info=True)

    def _build_from_pg(self):
        """从 PostgreSQL 系统表动态读取所有元数据"""
        with SessionLocal() as db:
            # 1. 获取所有用户表的列信息 + 注释（一条 SQL 搞定）
            schema_sql = text("""
                SELECT
                    t.relname AS table_name,
                    obj_description(t.oid, 'pg_class') AS table_comment,
                    a.attname AS column_name,
                    pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                    a.attnotnull AS not_null,
                    col_description(t.oid, a.attnum) AS column_comment,
                    COALESCE(
                        (SELECT true FROM pg_index i 
                         WHERE i.indrelid = t.oid AND a.attnum = ANY(i.indkey) AND i.indisprimary),
                        false
                    ) AS is_pk
                FROM pg_class t
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum > 0 AND NOT a.attisdropped
                WHERE t.relkind = 'r'
                  AND t.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
                ORDER BY t.relname, a.attnum
            """)
            rows = db.execute(schema_sql).fetchall()

            # 按表分组
            table_columns: dict[str, list[ColumnInfo]] = {}
            table_comments: dict[str, str] = {}
            for row in rows:
                tname = row.table_name
                if tname not in table_columns:
                    table_columns[tname] = []
                    table_comments[tname] = (row.table_comment or "").strip()
                table_columns[tname].append(ColumnInfo(
                    name=row.column_name,
                    type=row.data_type,
                    nullable=not row.not_null,
                    comment=(row.column_comment or "").strip(),
                    is_pk=row.is_pk,
                ))

            self.total_tables = len(table_columns)

            # 2. 逐个表获取行数和日期范围
            for tname, columns in table_columns.items():
                try:
                    # 行数
                    result = db.execute(text(f'SELECT COUNT(*) FROM "{tname}"'))
                    row_count = result.fetchone()[0]
                    self.total_rows += row_count

                    # 主键列
                    key_columns = [c.name for c in columns if c.is_pk]

                    # 日期范围 — 优先取业务日期列
                    date_min, date_max = None, None
                    priority_date_cols = ["trade_date", "ann_date", "end_date", "f_ann_date"]
                    col_names = [c.name for c in columns]
                    for pcol in priority_date_cols:
                        if pcol in col_names:
                            try:
                                result = db.execute(
                                    text(f'SELECT MIN("{pcol}"), MAX("{pcol}") FROM "{tname}"')
                                )
                                mn, mx = result.fetchone()
                                if mn and mx:
                                    date_min, date_max = str(mn), str(mx)
                                    break
                            except Exception:
                                pass

                    # 全局日期范围（从 daily_kline 取）
                    if tname == "daily_kline" and date_min and date_max:
                        self.earliest_trade_date = date_min
                        self.latest_trade_date = date_max

                    self.tables[tname] = TableInfo(
                        name=tname,
                        description=table_comments.get(tname, ""),
                        row_count=row_count,
                        date_min=date_min,
                        date_max=date_max,
                        columns=columns,
                        key_columns=key_columns,
                        data_freshness=_parse_freshness(date_max),
                    )
                except Exception as e:
                    logger.warning(f"[DataCatalog] 扫描表 {tname} 失败: {e}")

    def to_prompt(self) -> str:
        """生成可注入 Agent Prompt 的数据地图"""
        if not self.tables:
            return "数据地图为空，数据库可能尚未初始化。"

        lines = [
            "## 🗺️ 数据地图 —— 你对数据了如指掌",
            "",
            f"**数据全景**: {self.total_tables} 张表, {self.total_rows:,} 条数据",
        ]
        if self.latest_trade_date:
            lines.append(f"**K线数据范围**: {self.earliest_trade_date} ~ {self.latest_trade_date}")
            lines.append(f"**最新交易日**: {self.latest_trade_date}")
        lines.append("")

        lines.append("### 核心数据表")
        lines.append("")

        # 业务表优先展示
        priority_tables = [
            "stocks", "daily_kline", "etfs", "etf_daily_kline",
            "financial_reports", "money_flow", "industry_aggregation",
            "macro_data", "stock_factors", "sentiment_data",
            "data_sync_status", "portfolios", "portfolio_positions",
            "analysis_records", "conversation_history",
            "agent_analysis_sessions", "agent_audit_logs",
        ]

        for tname in priority_tables:
            if tname in self.tables:
                t = self.tables[tname]
                desc = t.description or "(无注释，建议添加 COMMENT ON TABLE)"
                lines.append(f"**{tname}** — {desc}")
                lines.append(f"  - 数据量: {t.row_count:,} 条")
                if t.date_min and t.date_max:
                    lines.append(f"  - 日期范围: {t.date_min} ~ {t.date_max}")
                lines.append(f"  - 新鲜度: {t.data_freshness}")
                if t.key_columns:
                    lines.append(f"  - 主键: {', '.join(t.key_columns)}")
                # 列出关键列（有注释的优先）
                cols_with_comment = [c for c in t.columns if c.comment]
                if cols_with_comment:
                    col_str = ", ".join(f"{c.name}({c.comment})" for c in cols_with_comment[:8])
                    lines.append(f"  - 字段: {col_str}")
                else:
                    key_cols = [c.name for c in t.columns[:8]]
                    lines.append(f"  - 字段: {', '.join(key_cols)}")
                lines.append("")

        # 其他表
        other_tables = [tname for tname in self.tables if tname not in priority_tables]
        if other_tables:
            lines.append("### 其他表")
            for tname in other_tables:
                t = self.tables[tname]
                lines.append(f"- **{tname}**: {t.row_count:,} 条, {t.data_freshness}")
            lines.append("")

        # 数据质量速查
        lines.append("### 数据质量速查")
        lines.append("")
        has_warning = False
        for tname in priority_tables:
            if tname in self.tables:
                t = self.tables[tname]
                if t.row_count == 0:
                    lines.append(f"- ⚠️ **{tname}**: 表为空，需要同步数据")
                    has_warning = True
                elif t.data_freshness.startswith("🔴"):
                    lines.append(f"- ⚠️ **{tname}**: {t.data_freshness}，数据可能过期")
                    has_warning = True
        if not has_warning:
            lines.append("- ✅ 所有数据表状态正常")
        lines.append("")

        return "\n".join(lines)

    def to_tool_result(self) -> str:
        """作为工具调用结果返回"""
        return self.to_prompt()


# 全局数据目录
_data_catalog: Optional[DataCatalog] = None


def get_data_catalog() -> DataCatalog:
    """获取全局数据目录实例（懒加载）"""
    global _data_catalog
    if _data_catalog is None:
        _data_catalog = DataCatalog()
    return _data_catalog


def refresh_data_catalog():
    """刷新数据目录"""
    global _data_catalog
    _data_catalog = DataCatalog()
    return _data_catalog


def build_catalog_prompt() -> str:
    """构建数据地图 Prompt，注入到 Agent 的 system prompt 中"""
    catalog = get_data_catalog()
    return catalog.to_prompt()