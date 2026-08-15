"""review_analysis Pipeline —— 投资复盘分析。

市场环境 → 持仓分析 → 归因分析 → 风险评估 → 改进建议 → 复盘报告
"""
from alpha_agent.pipeline.base import Pipeline
from alpha_agent.utils.logger import logger


def _step_market_env(params: dict, **kwargs) -> dict:
    from alpha_agent.infra.db.database import SessionLocal
    from sqlalchemy import text

    results = {}
    try:
        with SessionLocal() as db:
            latest = db.execute(text("SELECT MAX(trade_date) FROM daily_kline"))
            latest_date = latest.fetchone()[0]
            results["latest_date"] = str(latest_date) if latest_date else None

            market = db.execute(text(f"""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN pct_chg > 0 THEN 1 ELSE 0 END) as up_count,
                    SUM(CASE WHEN pct_chg < 0 THEN 1 ELSE 0 END) as down_count,
                    AVG(CAST(pct_chg AS FLOAT)) as avg_pct,
                    SUM(CAST(amount AS FLOAT)) as total_amount
                FROM daily_kline
                WHERE trade_date = '{latest_date}'
            """))
            m = market.fetchone()
            if m:
                results["total_stocks"] = m.total
                results["up_count"] = m.up_count
                results["down_count"] = m.down_count
                results["flat_count"] = m.total - m.up_count - m.down_count
                results["avg_pct"] = float(m.avg_pct) if m.avg_pct else 0
                results["total_amount"] = float(m.total_amount) if m.total_amount else 0
                results["up_ratio"] = round(m.up_count / m.total * 100, 1) if m.total > 0 else 0

            industries = db.execute(text(f"""
                SELECT industry, avg_pct_chg, stock_count, up_count, down_count
                FROM industry_aggregation
                WHERE trade_date = '{latest_date}'
                ORDER BY avg_pct_chg DESC
            """))
            ind_list = []
            for ind in industries.fetchall():
                ind_list.append({
                    "name": ind.industry,
                    "avg_pct": float(ind.avg_pct_chg),
                    "count": ind.stock_count,
                    "up": ind.up_count,
                    "down": ind.down_count,
                })
            results["top_industries"] = ind_list[:5]
            results["bottom_industries"] = ind_list[-5:] if len(ind_list) >= 5 else ind_list
            results["industry_count"] = len(ind_list)

            if ind_list:
                spread = ind_list[0]["avg_pct"] - ind_list[-1]["avg_pct"]
                results["industry_spread"] = round(spread, 2)
                results["structural"] = spread > 5

    except Exception as e:
        logger.error(f"[review_analysis] 市场环境分析失败: {e}")
        results["error"] = str(e)

    return {"market_env": results}


def _step_portfolio_analysis(params: dict, **kwargs) -> dict:
    from alpha_agent.infra.db.database import SessionLocal
    from sqlalchemy import text

    portfolio_id = params.get("portfolio_id", "")
    results = {"positions": [], "summary": {}}

    try:
        with SessionLocal() as db:
            if portfolio_id:
                pf = db.execute(text("""
                    SELECT portfolio_id, name, initial_capital, created_at
                    FROM portfolios WHERE portfolio_id = :pid
                """), {"pid": portfolio_id}).fetchone()
                if pf:
                    results["summary"]["portfolio_id"] = pf.portfolio_id
                    results["summary"]["name"] = pf.name
                    results["summary"]["initial_capital"] = float(pf.initial_capital)

                    positions = db.execute(text("""
                        SELECT p.ts_code, s.name, p.shares, p.cost_price
                        FROM portfolio_positions p
                        JOIN stocks s ON p.ts_code = s.ts_code
                        WHERE p.portfolio_id = :pid
                    """), {"pid": portfolio_id}).fetchall()

                    total_cost = 0
                    for pos in positions:
                        kline = db.execute(text(f"""
                            SELECT close, pct_chg, amount
                            FROM daily_kline
                            WHERE ts_code = '{pos.ts_code}'
                            ORDER BY trade_date DESC LIMIT 1
                        """)).fetchone()

                        current_price = float(kline[0]) if kline else float(pos.cost_price)
                        pnl = (current_price - float(pos.cost_price)) * pos.shares
                        pnl_pct = (current_price - float(pos.cost_price)) / float(pos.cost_price) * 100

                        pos_data = {
                            "ts_code": pos.ts_code,
                            "name": pos.name,
                            "shares": pos.shares,
                            "cost_price": float(pos.cost_price),
                            "current_price": current_price,
                            "pnl": round(pnl, 2),
                            "pnl_pct": round(pnl_pct, 2),
                            "latest_pct": float(kline[1]) if kline and kline[1] else 0,
                            "market_value": round(current_price * pos.shares, 2),
                        }
                        results["positions"].append(pos_data)
                        total_cost += float(pos.cost_price) * pos.shares

                    total_pnl = sum(p["pnl"] for p in results["positions"])
                    total_mv = sum(p["market_value"] for p in results["positions"])
                    results["summary"]["total_positions"] = len(results["positions"])
                    results["summary"]["total_cost"] = round(total_cost, 2)
                    results["summary"]["total_pnl"] = round(total_pnl, 2)
                    results["summary"]["total_market_value"] = round(total_mv, 2)
                    results["summary"]["return_pct"] = round(total_pnl / total_cost * 100, 2) if total_cost > 0 else 0
                    results["summary"]["win_count"] = sum(1 for p in results["positions"] if p["pnl"] > 0)
                    results["summary"]["lose_count"] = sum(1 for p in results["positions"] if p["pnl"] < 0)
                    results["mode"] = "portfolio"
            else:
                results["mode"] = "market"
                results["summary"]["mode"] = "market"

                latest = db.execute(text("SELECT MAX(trade_date) FROM daily_kline"))
                latest_date = latest.fetchone()[0]

                leaders = db.execute(text(f"""
                    SELECT d.ts_code, s.name, d.pct_chg, d.amount, d.vol
                    FROM daily_kline d
                    JOIN stocks s ON d.ts_code = s.ts_code
                    WHERE d.trade_date = '{latest_date}'
                    ORDER BY d.pct_chg DESC
                    LIMIT 10
                """))
                results["top_gainers"] = []
                for row in leaders.fetchall():
                    results["top_gainers"].append({
                        "ts_code": row[0],
                        "name": row[1],
                        "pct_chg": float(row[2]),
                        "amount": float(row[3]) if row[3] else 0,
                    })

                losers = db.execute(text(f"""
                    SELECT d.ts_code, s.name, d.pct_chg, d.amount, d.vol
                    FROM daily_kline d
                    JOIN stocks s ON d.ts_code = s.ts_code
                    WHERE d.trade_date = '{latest_date}'
                    ORDER BY d.pct_chg ASC
                    LIMIT 10
                """))
                results["top_losers"] = []
                for row in losers.fetchall():
                    results["top_losers"].append({
                        "ts_code": row[0],
                        "name": row[1],
                        "pct_chg": float(row[2]),
                        "amount": float(row[3]) if row[3] else 0,
                    })

                turnover = db.execute(text(f"""
                    SELECT f.ts_code, s.name, f.volume_ratio_5d, d.pct_chg
                    FROM stock_factors f
                    JOIN stocks s ON f.ts_code = s.ts_code
                    JOIN daily_kline d ON f.ts_code = d.ts_code AND d.trade_date = f.trade_date
                    WHERE f.trade_date = (SELECT MAX(trade_date) FROM stock_factors)
                    ORDER BY f.volume_ratio_5d DESC
                    LIMIT 10
                """))
                results["high_turnover"] = []
                for row in turnover.fetchall():
                    results["high_turnover"].append({
                        "ts_code": row[0],
                        "name": row[1],
                        "turnover_rate": float(row[2]) if row[2] else 0,
                        "pct_chg": float(row[3]) if row[3] else 0,
                    })

                results["summary"]["gainers_count"] = len(results["top_gainers"])
                results["summary"]["losers_count"] = len(results["top_losers"])

    except Exception as e:
        logger.error(f"[review_analysis] 持仓分析失败: {e}")
        results["error"] = str(e)
        results["mode"] = "market"

    return {"portfolio": results}


def _step_attribution_analysis(params: dict, **kwargs) -> dict:
    market_env = kwargs.get("market_env", {})
    portfolio = kwargs.get("portfolio", {})

    attribution = {}

    try:
        if market_env.get("avg_pct") is not None:
            avg_pct = market_env["avg_pct"]
            if avg_pct > 0.5:
                attribution["market_direction"] = "上涨"
                attribution["market_score"] = 3
            elif avg_pct < -0.5:
                attribution["market_direction"] = "下跌"
                attribution["market_score"] = -3
            else:
                attribution["market_direction"] = "震荡"
                attribution["market_score"] = 0

            up_ratio = market_env.get("up_ratio", 50)
            if up_ratio > 70:
                attribution["market_sentiment"] = "乐观"
            elif up_ratio < 30:
                attribution["market_sentiment"] = "悲观"
            else:
                attribution["market_sentiment"] = "中性"

            if market_env.get("structural"):
                attribution["market_pattern"] = "结构性行情"
            else:
                attribution["market_pattern"] = "普涨/普跌行情"

        mode = portfolio.get("mode", "market")

        if mode == "portfolio":
            pos_list = portfolio.get("positions", [])
            if pos_list:
                total_pnl = portfolio.get("summary", {}).get("total_pnl", 0)
                winners = [p for p in pos_list if p["pnl"] > 0]
                losers = [p for p in pos_list if p["pnl"] < 0]

                if winners:
                    best = max(winners, key=lambda x: x["pnl_pct"])
                    attribution["best_performer"] = {
                        "name": best["name"],
                        "code": best["ts_code"],
                        "pnl_pct": best["pnl_pct"],
                    }
                if losers:
                    worst = min(losers, key=lambda x: x["pnl_pct"])
                    attribution["worst_performer"] = {
                        "name": worst["name"],
                        "code": worst["ts_code"],
                        "pnl_pct": worst["pnl_pct"],
                    }

                if total_pnl > 0:
                    attribution["overall_result"] = "盈利"
                    attribution["key_driver"] = best["name"] if winners else "无明显驱动"
                elif total_pnl < 0:
                    attribution["overall_result"] = "亏损"
                    attribution["key_drag"] = worst["name"] if losers else "无明显拖累"
                else:
                    attribution["overall_result"] = "持平"

                win_rate = len(winners) / len(pos_list) * 100 if pos_list else 0
                attribution["win_rate"] = round(win_rate, 1)

                if winners and losers:
                    avg_win = sum(w["pnl_pct"] for w in winners) / len(winners)
                    avg_loss = sum(abs(l["pnl_pct"]) for l in losers) / len(losers)
                    attribution["avg_win"] = round(avg_win, 2)
                    attribution["avg_loss"] = round(avg_loss, 2)
                    attribution["profit_loss_ratio"] = round(avg_win / avg_loss, 2) if avg_loss > 0 else float("inf")
        else:
            top_gainers = portfolio.get("top_gainers", [])
            top_losers = portfolio.get("top_losers", [])
            high_turnover = portfolio.get("high_turnover", [])

            if top_gainers:
                best = top_gainers[0]
                attribution["market_best"] = {
                    "name": best["name"],
                    "code": best["ts_code"],
                    "pct_chg": best["pct_chg"],
                }
            if top_losers:
                worst = top_losers[0]
                attribution["market_worst"] = {
                    "name": worst["name"],
                    "code": worst["ts_code"],
                    "pct_chg": worst["pct_chg"],
                }

            if high_turnover:
                hottest = high_turnover[0]
                attribution["hottest_stock"] = {
                    "name": hottest["name"],
                    "code": hottest["ts_code"],
                    "turnover_rate": hottest["turnover_rate"],
                }

            attribution["review_mode"] = "市场复盘"

    except Exception as e:
        logger.error(f"[review_analysis] 归因分析失败: {e}")
        attribution["error"] = str(e)

    return {"attribution": attribution}


def _step_synthesize_report(params: dict, **kwargs) -> dict:
    market_env = kwargs.get("market_env", {})
    portfolio = kwargs.get("portfolio", {})
    attribution = kwargs.get("attribution", {})

    mode = portfolio.get("mode", "market")
    is_portfolio = mode == "portfolio" and portfolio.get("positions")

    lines = ["# 投资复盘报告", ""]

    lines.append("## 一、市场环境")
    if market_env.get("latest_date"):
        lines.append(f"- **日期**: {market_env['latest_date']}")
    if market_env.get("avg_pct") is not None:
        direction = "上涨" if market_env["avg_pct"] > 0 else "下跌"
        lines.append(f"- **市场表现**: {direction} {market_env['avg_pct']:.2f}%")
    if market_env.get("up_count") is not None:
        lines.append(f"- **涨跌比**: {market_env['up_count']}涨/{market_env['down_count']}跌")
        lines.append(f"- **上涨占比**: {market_env['up_ratio']}%")
    if market_env.get("total_amount"):
        lines.append(f"- **总成交额**: {market_env['total_amount'] / 1e8:.0f}亿")
    if market_env.get("top_industries"):
        lines.append("- **领涨板块**:")
        for ind in market_env["top_industries"][:3]:
            lines.append(f"  - {ind['name']}: {ind['avg_pct']:.2f}%")
    if market_env.get("bottom_industries"):
        lines.append("- **领跌板块**:")
        for ind in market_env["bottom_industries"][-3:]:
            lines.append(f"  - {ind['name']}: {ind['avg_pct']:.2f}%")
    if market_env.get("structural"):
        lines.append("- ⚠️ **市场特征**: 结构性行情，板块分化严重")
    lines.append("")

    if is_portfolio:
        lines.append("## 二、持仓分析")
        summary = portfolio.get("summary", {})
        if summary:
            lines.append(f"- **组合名称**: {summary.get('name', '-')}")
            lines.append(f"- **持仓数量**: {summary.get('total_positions', 0)}只")
            if summary.get("total_cost"):
                lines.append(f"- **总成本**: {summary['total_cost']:,.2f}")
            if summary.get("total_market_value"):
                lines.append(f"- **总市值**: {summary['total_market_value']:,.2f}")
            if summary.get("total_pnl") is not None:
                pnl_emoji = "✅" if summary["total_pnl"] > 0 else "❌" if summary["total_pnl"] < 0 else "➖"
                lines.append(f"- **总盈亏**: {pnl_emoji} {summary['total_pnl']:,.2f} ({summary.get('return_pct', 0):.2f}%)")
            if summary.get("win_count") is not None:
                lines.append(f"- **盈亏分布**: {summary['win_count']}盈/{summary['lose_count']}亏")

            positions = portfolio.get("positions", [])
            if positions:
                lines.append("\n### 持仓明细")
                lines.append("| 股票 | 成本价 | 现价 | 盈亏% | 市值 |")
                lines.append("|------|--------|------|-------|------|")
                for p in positions:
                    pnl_emoji = "🟢" if p["pnl"] > 0 else "🔴" if p["pnl"] < 0 else "⚪"
                    lines.append(f"| {p['name']} ({p['ts_code']}) | {p['cost_price']:.2f} | {p['current_price']:.2f} | {pnl_emoji} {p['pnl_pct']:.2f}% | {p['market_value']:,.0f} |")
        lines.append("")
    else:
        lines.append("## 二、市场热点")
        top_gainers = portfolio.get("top_gainers", [])
        top_losers = portfolio.get("top_losers", [])
        high_turnover = portfolio.get("high_turnover", [])

        if top_gainers:
            lines.append("\n### 涨停榜 TOP10")
            lines.append("| 排名 | 股票 | 涨幅 | 成交额(万) |")
            lines.append("|------|------|------|------------|")
            for i, g in enumerate(top_gainers, 1):
                lines.append(f"| {i} | {g['name']} ({g['ts_code']}) | {g['pct_chg']:.2f}% | {g['amount']/1e4:,.0f} |")

        if top_losers:
            lines.append("\n### 跌停榜 TOP10")
            lines.append("| 排名 | 股票 | 跌幅 | 成交额(万) |")
            lines.append("|------|------|------|------------|")
            for i, l in enumerate(top_losers, 1):
                lines.append(f"| {i} | {l['name']} ({l['ts_code']}) | {l['pct_chg']:.2f}% | {l['amount']/1e4:,.0f} |")

        if high_turnover:
            lines.append("\n### 高换手榜 TOP10")
            lines.append("| 排名 | 股票 | 换手率 | 涨跌幅 |")
            lines.append("|------|------|--------|--------|")
            for i, t in enumerate(high_turnover, 1):
                lines.append(f"| {i} | {t['name']} ({t['ts_code']}) | {t['turnover_rate']:.2f}% | {t['pct_chg']:.2f}% |")

        lines.append("")

    lines.append("## 三、归因分析")
    if attribution.get("market_direction"):
        lines.append(f"- **市场方向**: {attribution['market_direction']}")
        lines.append(f"- **市场情绪**: {attribution.get('market_sentiment', '-')}")
    if attribution.get("market_pattern"):
        lines.append(f"- **行情特征**: {attribution['market_pattern']}")

    if is_portfolio:
        if attribution.get("overall_result"):
            lines.append(f"- **组合结果**: {attribution['overall_result']}")
        if attribution.get("best_performer"):
            lines.append(f"- **最佳持仓**: {attribution['best_performer']['name']} ({attribution['best_performer']['pnl_pct']:.2f}%)")
        if attribution.get("worst_performer"):
            lines.append(f"- **最差持仓**: {attribution['worst_performer']['name']} ({attribution['worst_performer']['pnl_pct']:.2f}%)")
        if attribution.get("win_rate") is not None:
            lines.append(f"- **胜率**: {attribution['win_rate']}%")
        if attribution.get("profit_loss_ratio") is not None:
            lines.append(f"- **盈亏比**: {attribution['profit_loss_ratio']}")
    else:
        if attribution.get("market_best"):
            lines.append(f"- **最强个股**: {attribution['market_best']['name']} ({attribution['market_best']['pct_chg']:.2f}%)")
        if attribution.get("market_worst"):
            lines.append(f"- **最弱个股**: {attribution['market_worst']['name']} ({attribution['market_worst']['pct_chg']:.2f}%)")
        if attribution.get("hottest_stock"):
            lines.append(f"- **最热个股**: {attribution['hottest_stock']['name']} (换手率 {attribution['hottest_stock']['turnover_rate']:.2f}%)")
    lines.append("")

    lines.append("## 四、风险评估与改进建议")
    suggestions = []

    if market_env.get("structural"):
        suggestions.append("- 💡 市场分化严重，建议聚焦强势板块，回避弱势板块")

    if is_portfolio:
        summary = portfolio.get("summary", {})
        positions = portfolio.get("positions", [])

        if attribution.get("win_rate") is not None and attribution["win_rate"] < 40:
            suggestions.append("- ⚠️ 胜率偏低，建议审视选股标准和入场时机")
        if attribution.get("profit_loss_ratio") is not None and attribution["profit_loss_ratio"] < 1:
            suggestions.append("- ⚠️ 盈亏比不足1，建议严格止损或优化卖出策略")

        if summary.get("total_positions", 0) > 0:
            if summary["win_count"] < summary["lose_count"]:
                suggestions.append("- ⚠️ 亏损持仓多于盈利持仓，建议检查个股选择逻辑")

        if positions:
            max_pos = max(positions, key=lambda x: x["market_value"])
            total_mv = summary.get("total_market_value", 1)
            concentration = max_pos["market_value"] / total_mv * 100 if total_mv > 0 else 0
            if concentration > 40:
                suggestions.append(f"- ⚠️ 集中度偏高: {max_pos['name']}占{concentration:.0f}%，建议分散持仓")
    else:
        up_ratio = market_env.get("up_ratio", 50)
        if up_ratio > 80:
            suggestions.append("- 🔥 市场普涨，注意追高风险，可适当获利了结")
        elif up_ratio < 20:
            suggestions.append("- 📉 市场普跌，控制仓位，关注超跌反弹机会")

        if market_env.get("top_industries"):
            top_ind = market_env["top_industries"][0]
            suggestions.append(f"- 💡 关注领涨板块: {top_ind['name']}（{top_ind['avg_pct']:.2f}%），可考虑相关标的")

        if market_env.get("bottom_industries"):
            bottom_ind = market_env["bottom_industries"][-1]
            suggestions.append(f"- ⚠️ 回避领跌板块: {bottom_ind['name']}（{bottom_ind['avg_pct']:.2f}%）")

        high_turnover = portfolio.get("high_turnover", [])
        if high_turnover and high_turnover[0].get("turnover_rate", 0) > 20:
            hottest = high_turnover[0]
            suggestions.append(f"- 🔍 高换手率个股 {hottest['name']}（{hottest['turnover_rate']:.1f}%），资金关注度高")

    if not suggestions:
        suggestions.append("- ✅ 各项指标良好，继续保持当前策略")

    for s in suggestions:
        lines.append(s)

    lines.append("")
    lines.append("---")
    lines.append("⚠️ 以上复盘分析仅供参考，不构成投资建议。投资有风险，入市需谨慎。")

    return {"report": "\n".join(lines)}


def register(registry):
    pipeline = Pipeline(
        name="review_analysis",
        description="投资复盘分析（市场环境→持仓分析→归因分析→风险评估→改进建议→复盘报告）",
        params_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "string", "description": "组合ID（可选），提供后分析持仓"},
            },
            "required": [],
        },
    )

    pipeline.add_step(
        name="市场环境分析",
        fn=_step_market_env,
        outputs=["market_env"],
    )
    pipeline.add_step(
        name="持仓分析",
        fn=_step_portfolio_analysis,
        outputs=["portfolio"],
        optional=True,
    )
    pipeline.add_step(
        name="归因分析",
        fn=_step_attribution_analysis,
        inputs=["market_env", "portfolio"],
        outputs=["attribution"],
    )
    pipeline.add_step(
        name="生成复盘报告",
        fn=_step_synthesize_report,
        inputs=["market_env", "portfolio", "attribution"],
        outputs=["report"],
    )

    registry.register(pipeline)
