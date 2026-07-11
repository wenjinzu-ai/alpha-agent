"""market_overview Pipeline —— 市场概览。

行情统计 → 行业涨跌 → 资金流向 → 异常检测 → 报告
"""
import math

from alpha_agent.pipeline.base import Pipeline
from alpha_agent.utils.logger import logger


def _step_market_stats(params: dict, **kwargs) -> dict:
    from alpha_agent.infra.db.database import SessionLocal
    from sqlalchemy import text

    results = {}
    try:
        with SessionLocal() as db:
            latest = db.execute(
                text("SELECT MAX(trade_date) FROM daily_kline")
            ).fetchone()
            if not latest or not latest[0]:
                return {"market_stats": "无K线数据"}

            trade_date = latest[0]
            results["trade_date"] = trade_date

            stats = db.execute(
                text("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN pct_chg > 0 THEN 1 ELSE 0 END) as up_count,
                        SUM(CASE WHEN pct_chg < 0 THEN 1 ELSE 0 END) as down_count,
                        SUM(CASE WHEN pct_chg = 0 THEN 1 ELSE 0 END) as flat_count,
                        COALESCE(AVG(pct_chg), 0) as avg_pct,
                        COALESCE(SUM(amount), 0) as total_amount
                    FROM daily_kline
                    WHERE trade_date = :date
                """),
                {"date": trade_date},
            ).fetchone()

            if stats:
                results["total"] = int(stats[0] or 0)
                results["up_count"] = int(stats[1] or 0)
                results["down_count"] = int(stats[2] or 0)
                results["flat_count"] = int(stats[3] or 0)
                results["avg_pct"] = round(float(stats[4] or 0), 2)
                results["total_amount"] = round(float(stats[5] or 0) / 1e8, 2)

            limit_stats = db.execute(
                text("""
                    SELECT
                        SUM(CASE WHEN pct_chg >= 9.9 THEN 1 ELSE 0 END) as limit_up,
                        SUM(CASE WHEN pct_chg <= -9.9 THEN 1 ELSE 0 END) as limit_down
                    FROM daily_kline
                    WHERE trade_date = :date
                """),
                {"date": trade_date},
            ).fetchone()

            if limit_stats:
                results["limit_up"] = int(limit_stats[0] or 0)
                results["limit_down"] = int(limit_stats[1] or 0)

    except Exception as e:
        logger.error(f"[market_overview] 行情统计失败: {e}")
        results["error"] = str(e)

    return {"market_stats": results}


def _step_industry_performance(params: dict, **kwargs) -> dict:
    from alpha_agent.infra.db.database import SessionLocal
    from sqlalchemy import text

    results = {}
    try:
        with SessionLocal() as db:
            rows = db.execute(
                text("""
                    SELECT industry, stock_count, avg_pct_chg, up_count, down_count, total_amount
                    FROM industry_aggregation
                    WHERE trade_date = (SELECT MAX(trade_date) FROM industry_aggregation)
                    ORDER BY avg_pct_chg DESC
                    LIMIT 30
                """)
            ).fetchall()

            if rows:
                top5 = rows[:5]
                bottom5 = rows[-5:] if len(rows) >= 5 else rows
                results["top_industries"] = [
                    {
                        "industry": r[0],
                        "stock_count": int(r[1] or 0),
                        "avg_pct_chg": round(float(r[2] or 0), 2),
                        "up_count": int(r[3] or 0),
                        "down_count": int(r[4] or 0),
                    }
                    for r in top5
                ]
                results["bottom_industries"] = [
                    {
                        "industry": r[0],
                        "stock_count": int(r[1] or 0),
                        "avg_pct_chg": round(float(r[2] or 0), 2),
                        "up_count": int(r[3] or 0),
                        "down_count": int(r[4] or 0),
                    }
                    for r in bottom5
                ]

    except Exception as e:
        logger.error(f"[market_overview] 行业分析失败: {e}")
        results["error"] = str(e)

    return {"industry_performance": results}


def _step_money_flow(params: dict, **kwargs) -> dict:
    from alpha_agent.infra.db.database import SessionLocal
    from sqlalchemy import text

    results = {}
    try:
        with SessionLocal() as db:
            flow = db.execute(
                text("""
                    SELECT trade_date,
                           SUM(main_net_inflow) as total_main_inflow
                    FROM money_flow
                    WHERE trade_date = (SELECT MAX(trade_date) FROM money_flow)
                    GROUP BY trade_date
                """)
            ).fetchone()

            if flow:
                results["trade_date"] = str(flow[0])
                total_inflow = float(flow[1] or 0)
                results["total_main_inflow"] = round(total_inflow / 1e4, 2)
                direction = "净流入" if total_inflow > 0 else "净流出"
                results["direction"] = direction

    except Exception as e:
        logger.error(f"[market_overview] 资金流向分析失败: {e}")
        results["error"] = str(e)

    return {"money_flow": results}


def _step_anomaly_detection(params: dict, **kwargs) -> dict:
    from alpha_agent.infra.db.database import SessionLocal
    from sqlalchemy import text

    market_stats = kwargs.get("market_stats", {})
    results = {"anomalies": []}

    try:
        with SessionLocal() as db:
            trade_date = market_stats.get("trade_date", "")
            if not trade_date:
                return {"anomaly_detection": results}

            surges = db.execute(
                text("""
                    SELECT s.name, k.ts_code, k.pct_chg, k.vol, k.amount
                    FROM daily_kline k
                    JOIN stocks s ON k.ts_code = s.ts_code
                    WHERE k.trade_date = :date AND k.pct_chg > 5
                    ORDER BY k.pct_chg DESC LIMIT 10
                """),
                {"date": trade_date},
            ).fetchall()

            for s in surges:
                pct = float(s[2]) if s[2] is not None else 0
                if math.isnan(pct):
                    continue
                results["anomalies"].append({
                    "type": "大幅上涨",
                    "name": s[0],
                    "ts_code": s[1],
                    "pct_chg": round(pct, 2),
                })

            plunges = db.execute(
                text("""
                    SELECT s.name, k.ts_code, k.pct_chg, k.vol, k.amount
                    FROM daily_kline k
                    JOIN stocks s ON k.ts_code = s.ts_code
                    WHERE k.trade_date = :date AND k.pct_chg < -5
                    ORDER BY k.pct_chg ASC LIMIT 10
                """),
                {"date": trade_date},
            ).fetchall()

            for s in plunges:
                pct = float(s[2]) if s[2] is not None else 0
                if math.isnan(pct):
                    continue
                results["anomalies"].append({
                    "type": "大幅下跌",
                    "name": s[0],
                    "ts_code": s[1],
                    "pct_chg": round(pct, 2),
                })

    except Exception as e:
        logger.error(f"[market_overview] 异常检测失败: {e}")
        results["error"] = str(e)

    return {"anomaly_detection": results}


def _step_synthesize(params: dict, **kwargs) -> dict:
    market_stats = kwargs.get("market_stats", {})
    industry_performance = kwargs.get("industry_performance", {})
    money_flow = kwargs.get("money_flow", {})
    anomaly_detection = kwargs.get("anomaly_detection", {})

    lines = []
    trade_date = market_stats.get("trade_date", "未知")

    lines.append(f"# 市场概览（{trade_date}）")
    lines.append("")

    if market_stats.get("total"):
        lines.append("## 行情统计")
        lines.append(f"- 交易股票数: {market_stats.get('total', 0)}")
        lines.append(f"- 上涨: {market_stats.get('up_count', 0)} | 下跌: {market_stats.get('down_count', 0)} | 平盘: {market_stats.get('flat_count', 0)}")
        lines.append(f"- 平均涨跌幅: {market_stats.get('avg_pct', 0)}%")
        lines.append(f"- 总成交额: {market_stats.get('total_amount', 0)}亿")
        lines.append(f"- 涨停: {market_stats.get('limit_up', 0)} | 跌停: {market_stats.get('limit_down', 0)}")
        lines.append("")

    if industry_performance.get("top_industries"):
        lines.append("## 行业涨跌")
        lines.append("**领涨行业:**")
        for ind in industry_performance["top_industries"][:5]:
            lines.append(f"  - {ind['industry']}: {ind['avg_pct_chg']}% ({ind['up_count']}涨/{ind['down_count']}跌)")
        if industry_performance.get("bottom_industries"):
            lines.append("**领跌行业:**")
            for ind in industry_performance["bottom_industries"][:5]:
                lines.append(f"  - {ind['industry']}: {ind['avg_pct_chg']}% ({ind['up_count']}涨/{ind['down_count']}跌)")
        lines.append("")

    if money_flow.get("total_main_inflow") is not None:
        direction = money_flow.get("direction", "净流入" if money_flow.get("total_main_inflow", 0) > 0 else "净流出")
        lines.append("## 资金流向")
        lines.append(f"- 主力资金{direction}: {abs(money_flow.get('total_main_inflow', 0))}亿")
        lines.append("")

    anomalies = anomaly_detection.get("anomalies", [])
    if anomalies:
        lines.append("## 异常信号")
        surges = [a for a in anomalies if a["type"] == "大幅上涨"]
        plunges = [a for a in anomalies if a["type"] == "大幅下跌"]
        if surges:
            lines.append("**大幅上涨:**")
            for a in surges[:5]:
                lines.append(f"  - {a['name']}({a['ts_code']}): {a['pct_chg']}%")
        if plunges:
            lines.append("**大幅下跌:**")
            for a in plunges[:5]:
                lines.append(f"  - {a['name']}({a['ts_code']}): {a['pct_chg']}%")
        lines.append("")

    lines.append("⚠️ 以上分析仅供参考，不构成投资建议。")

    return {"report": "\n".join(lines)}


def register(registry):
    pipeline = Pipeline(
        name="market_overview",
        description="市场概览（行情统计→行业涨跌→资金流向→异常检测→报告）",
        params_schema={
            "type": "object",
            "properties": {},
        },
    )

    pipeline.add_step(
        name="行情统计",
        fn=_step_market_stats,
        outputs=["market_stats"],
    )
    pipeline.add_step(
        name="行业涨跌",
        fn=_step_industry_performance,
        outputs=["industry_performance"],
    )
    pipeline.add_step(
        name="资金流向",
        fn=_step_money_flow,
        outputs=["money_flow"],
        optional=True,
    )
    pipeline.add_step(
        name="异常检测",
        fn=_step_anomaly_detection,
        inputs=["market_stats"],
        outputs=["anomaly_detection"],
        optional=True,
    )
    pipeline.add_step(
        name="综合报告",
        fn=_step_synthesize,
        inputs=["market_stats", "industry_performance", "money_flow", "anomaly_detection"],
        outputs=["report"],
    )

    registry.register(pipeline)