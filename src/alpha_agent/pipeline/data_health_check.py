"""data_health_check Pipeline —— 数据健康检查。

全表扫描 → 缺失检测 → 新鲜度评估 → 修复建议
"""
from alpha_agent.pipeline.base import Pipeline
from alpha_agent.utils.logger import logger


def _step_scan_tables(params: dict, **kwargs) -> dict:
    from alpha_agent.infra.db.database import SessionLocal
    from sqlalchemy import text

    tables_to_check = [
        ("stocks", "股票列表"),
        ("daily_kline", "股票日K线"),
        ("etfs", "ETF列表"),
        ("etf_daily_kline", "ETF日K线"),
        ("financial_reports", "财务报告"),
        ("money_flow", "资金流向"),
        ("industry_aggregation", "行业聚合"),
        ("macro_data", "宏观数据"),
        ("stock_factors", "选股因子"),
    ]

    results = {}
    try:
        with SessionLocal() as db:
            for table_name, display_name in tables_to_check:
                try:
                    count_row = db.execute(
                        text(f'SELECT COUNT(*) FROM "{table_name}"')
                    ).fetchone()
                    count = int(count_row[0]) if count_row else 0

                    latest_date = None
                    date_columns = {
                        "stocks": "list_date",
                        "daily_kline": "trade_date",
                        "etfs": "list_date",
                        "etf_daily_kline": "trade_date",
                        "financial_reports": "end_date",
                        "money_flow": "trade_date",
                        "industry_aggregation": "trade_date",
                        "macro_data": "indicator_date",
                        "stock_factors": "trade_date",
                    }

                    date_col = date_columns.get(table_name)
                    if date_col and count > 0:
                        try:
                            date_row = db.execute(
                                text(f'SELECT MAX("{date_col}") FROM "{table_name}"')
                            ).fetchone()
                            latest_date = str(date_row[0]) if date_row and date_row[0] else None
                        except Exception:
                            pass

                    results[table_name] = {
                        "display_name": display_name,
                        "count": count,
                        "latest_date": latest_date,
                        "status": "empty" if count == 0 else "has_data",
                    }

                except Exception as e:
                    results[table_name] = {
                        "display_name": display_name,
                        "count": 0,
                        "latest_date": None,
                        "status": "error",
                        "error": str(e),
                    }

    except Exception as e:
        logger.error(f"[data_health_check] 全表扫描失败: {e}")
        return {"table_scan": {"error": str(e)}}

    return {"table_scan": results}


def _step_freshness_check(params: dict, **kwargs) -> dict:
    from datetime import datetime, timedelta

    table_scan = kwargs.get("table_scan", {})
    results = {}

    today = datetime.now().strftime("%Y%m%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    weekday = datetime.now().weekday()

    for table_name, info in table_scan.items():
        if not isinstance(info, dict) or info.get("status") == "error":
            continue

        latest_date = info.get("latest_date")
        if not latest_date:
            results[table_name] = {
                **info,
                "freshness": "无数据",
                "days_behind": None,
            }
            continue

        try:
            if len(latest_date) == 8 and latest_date.isdigit():
                latest_dt = datetime.strptime(latest_date, "%Y%m%d")
            elif "-" in latest_date:
                latest_dt = datetime.strptime(latest_date[:10], "%Y-%m-%d")
            else:
                results[table_name] = {**info, "freshness": "未知格式", "days_behind": None}
                continue

            days_behind = (datetime.now() - latest_dt).days

            if table_name in ("daily_kline", "money_flow", "industry_aggregation", "stock_factors"):
                if weekday < 5:
                    expected = yesterday
                else:
                    expected = (datetime.now() - timedelta(days=weekday - 4)).strftime("%Y%m%d")

                if days_behind <= 1:
                    freshness = "新鲜"
                elif days_behind <= 3:
                    freshness = "轻微落后"
                else:
                    freshness = "严重落后"

            elif table_name in ("stocks", "etfs"):
                if days_behind <= 7:
                    freshness = "新鲜"
                elif days_behind <= 30:
                    freshness = "轻微落后"
                else:
                    freshness = "严重落后"

            elif table_name in ("financial_reports", "macro_data"):
                if days_behind <= 90:
                    freshness = "新鲜"
                elif days_behind <= 180:
                    freshness = "轻微落后"
                else:
                    freshness = "严重落后"

            else:
                if days_behind <= 7:
                    freshness = "新鲜"
                elif days_behind <= 30:
                    freshness = "轻微落后"
                else:
                    freshness = "严重落后"

            results[table_name] = {
                **info,
                "freshness": freshness,
                "days_behind": days_behind,
            }

        except Exception as e:
            results[table_name] = {**info, "freshness": "解析失败", "days_behind": None}

    return {"freshness_check": results}


def _step_repair_suggestions(params: dict, **kwargs) -> dict:
    freshness_check = kwargs.get("freshness_check", {})

    suggestions = []

    sync_commands = {
        "stocks": "sync_stock_list",
        "daily_kline": "sync_stock_kline",
        "etfs": "sync_etf_list",
        "etf_daily_kline": "sync_etf_kline",
        "financial_reports": "sync_financial_data",
        "money_flow": "sync_money_flow",
        "industry_aggregation": "sync_industry_aggregation",
        "macro_data": "sync_macro_data",
        "stock_factors": "sync_stock_factors",
    }

    for table_name, info in freshness_check.items():
        if not isinstance(info, dict):
            continue

        status = info.get("status", "")
        freshness = info.get("freshness", "")
        days_behind = info.get("days_behind")

        if status == "empty":
            suggestions.append({
                "table": table_name,
                "display_name": info.get("display_name", table_name),
                "issue": "表为空，无数据",
                "priority": "高",
                "action": f"同步{info.get('display_name', table_name)}数据",
                "command": sync_commands.get(table_name, ""),
            })

        elif freshness == "严重落后":
            suggestions.append({
                "table": table_name,
                "display_name": info.get("display_name", table_name),
                "issue": f"数据落后{days_behind}天",
                "priority": "高",
                "action": f"更新{info.get('display_name', table_name)}数据",
                "command": sync_commands.get(table_name, ""),
            })

        elif freshness == "轻微落后":
            suggestions.append({
                "table": table_name,
                "display_name": info.get("display_name", table_name),
                "issue": f"数据落后{days_behind}天",
                "priority": "中",
                "action": f"更新{info.get('display_name', table_name)}数据",
                "command": sync_commands.get(table_name, ""),
            })

    return {"repair_suggestions": suggestions}


def _step_synthesize(params: dict, **kwargs) -> dict:
    table_scan = kwargs.get("table_scan", {})
    freshness_check = kwargs.get("freshness_check", {})
    repair_suggestions = kwargs.get("repair_suggestions", [])

    lines = []
    lines.append("# 数据健康检查报告")
    lines.append("")

    lines.append("## 各表状态")
    lines.append(f"{'表名':<20} {'中文名':<12} {'记录数':<10} {'最新日期':<14} {'新鲜度':<10}")
    lines.append("-" * 70)

    for table_name, info in freshness_check.items():
        if not isinstance(info, dict):
            continue
        display = info.get("display_name", table_name)
        count = info.get("count", 0)
        latest = info.get("latest_date", "-") or "-"
        freshness = info.get("freshness", "-")

        emoji = {
            "新鲜": "🟢",
            "轻微落后": "🟡",
            "严重落后": "🔴",
            "无数据": "🔴",
            "未知格式": "⚪",
            "解析失败": "⚪",
        }.get(freshness, "⚪")

        lines.append(f"{table_name:<20} {display:<12} {count:<10} {latest:<14} {emoji}{freshness}")

    lines.append("")

    if repair_suggestions:
        lines.append("## 修复建议")
        high = [s for s in repair_suggestions if s.get("priority") == "高"]
        medium = [s for s in repair_suggestions if s.get("priority") == "中"]

        if high:
            lines.append("**高优先级:**")
            for s in high:
                lines.append(f"  - {s['display_name']}: {s['issue']} → {s['action']}")
        if medium:
            lines.append("**中优先级:**")
            for s in medium:
                lines.append(f"  - {s['display_name']}: {s['issue']} → {s['action']}")

        lines.append("")
        lines.append("## 快速修复命令")
        lines.append("```python")
        lines.append("from alpha_agent.infra.sync.service import DataSyncService")
        lines.append("sync = DataSyncService()")
        for s in high:
            cmd = s.get("command", "")
            if cmd:
                lines.append(f"sync.{cmd}()")
        lines.append("```")
    else:
        lines.append("✅ 所有数据状态正常，无需修复。")

    return {"report": "\n".join(lines)}


def register(registry):
    pipeline = Pipeline(
        name="data_health_check",
        description="数据健康检查（全表扫描→缺失检测→新鲜度评估→修复建议）",
        params_schema={
            "type": "object",
            "properties": {},
        },
    )

    pipeline.add_step(
        name="全表扫描",
        fn=_step_scan_tables,
        outputs=["table_scan"],
    )
    pipeline.add_step(
        name="新鲜度评估",
        fn=_step_freshness_check,
        inputs=["table_scan"],
        outputs=["freshness_check"],
    )
    pipeline.add_step(
        name="修复建议",
        fn=_step_repair_suggestions,
        inputs=["freshness_check"],
        outputs=["repair_suggestions"],
    )
    pipeline.add_step(
        name="综合报告",
        fn=_step_synthesize,
        inputs=["table_scan", "freshness_check", "repair_suggestions"],
        outputs=["report"],
    )

    registry.register(pipeline)