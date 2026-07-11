"""stock_analysis Pipeline —— 个股综合分析。

基本面 → 技术面 → 风控 → 综合评级 → 报告
"""
from alpha_agent.pipeline.base import Pipeline
from alpha_agent.utils.logger import logger


def _step_fundamental(params: dict, **kwargs) -> dict:
    from alpha_agent.infra.db.database import SessionLocal
    from sqlalchemy import text

    ts_code = params.get("ts_code", "")
    if not ts_code:
        return {"fundamental": "错误: 未提供股票代码"}

    results = {}
    try:
        with SessionLocal() as db:
            stock = db.execute(
                text("SELECT name, industry FROM stocks WHERE ts_code = :code LIMIT 1"),
                {"code": ts_code},
            ).fetchone()
            if stock:
                results["name"] = stock[0]
                results["industry"] = stock[1]

            kline = db.execute(
                text("""
                    SELECT trade_date, close, pct_chg, vol, amount
                    FROM daily_kline
                    WHERE ts_code = :code
                    ORDER BY trade_date DESC LIMIT 60
                """),
                {"code": ts_code},
            ).fetchall()

            if kline:
                latest = kline[0]
                results["latest_date"] = latest[0]
                results["latest_close"] = float(latest[1])
                results["latest_pct_chg"] = float(latest[2]) if latest[2] else 0

                closes = [float(k[1]) for k in kline if k[1]]
                if len(closes) >= 20:
                    results["ma20"] = round(sum(closes[:20]) / 20, 2)
                if len(closes) >= 5:
                    results["ma5"] = round(sum(closes[:5]) / 5, 2)

                pct_changes = [float(k[2]) for k in kline[:20] if k[2]]
                if pct_changes:
                    results["avg_pct_20d"] = round(sum(pct_changes) / len(pct_changes), 2)

            fin = db.execute(
                text("""
                    SELECT end_date, revenue, net_profit, roe, eps
                    FROM financial_reports
                    WHERE ts_code = :code
                    ORDER BY end_date DESC LIMIT 4
                """),
                {"code": ts_code},
            ).fetchall()

            if fin:
                results["financial_reports"] = [
                    {
                        "end_date": str(f[0]),
                        "revenue": float(f[1]) if f[1] else None,
                        "net_profit": float(f[2]) if f[2] else None,
                        "roe": float(f[3]) if f[3] else None,
                        "eps": float(f[4]) if f[4] else None,
                    }
                    for f in fin
                ]

    except Exception as e:
        logger.error(f"[stock_analysis] 基本面分析失败: {e}")
        results["fundamental_error"] = str(e)

    return {"fundamental": results}


def _step_technical(params: dict, **kwargs) -> dict:
    from alpha_agent.infra.db.database import SessionLocal
    from sqlalchemy import text

    ts_code = params.get("ts_code", "")
    if not ts_code:
        return {"technical": "错误: 未提供股票代码"}

    results = {}
    try:
        with SessionLocal() as db:
            kline = db.execute(
                text("""
                    SELECT trade_date, open, high, low, close, vol, amount, pct_chg
                    FROM daily_kline
                    WHERE ts_code = :code
                    ORDER BY trade_date DESC LIMIT 60
                """),
                {"code": ts_code},
            ).fetchall()

            if not kline:
                return {"technical": "无K线数据"}

            closes = [float(k[4]) for k in kline if k[4]]
            vols = [float(k[5]) for k in kline if k[5]]
            pct_changes = [float(k[7]) for k in kline if k[7]]

            if len(closes) >= 20:
                ma5 = sum(closes[:5]) / 5
                ma10 = sum(closes[:10]) / 10
                ma20 = sum(closes[:20]) / 20
                current = closes[0]

                if ma5 > ma10 > ma20:
                    results["trend"] = "多头排列（看涨）"
                elif ma5 < ma10 < ma20:
                    results["trend"] = "空头排列（看跌）"
                else:
                    results["trend"] = "震荡整理"

                results["ma5"] = round(ma5, 2)
                results["ma10"] = round(ma10, 2)
                results["ma20"] = round(ma20, 2)
                results["price_vs_ma20"] = "上方" if current > ma20 else "下方"
                results["price_vs_ma5"] = "上方" if current > ma5 else "下方"

            if len(pct_changes) >= 20:
                up_days = sum(1 for p in pct_changes[:20] if p > 0)
                results["up_ratio_20d"] = f"{up_days}/20"

                max_up = max(pct_changes[:20])
                max_down = min(pct_changes[:20])
                results["max_gain_20d"] = round(max_up, 2)
                results["max_loss_20d"] = round(max_down, 2)

            if len(vols) >= 10:
                avg_vol_10 = sum(vols[:10]) / 10
                avg_vol_5 = sum(vols[:5]) / 5
                vol_ratio = avg_vol_5 / avg_vol_10 if avg_vol_10 > 0 else 1
                results["vol_ratio"] = round(vol_ratio, 2)
                if vol_ratio > 1.5:
                    results["vol_signal"] = "放量"
                elif vol_ratio < 0.7:
                    results["vol_signal"] = "缩量"
                else:
                    results["vol_signal"] = "正常"

            factor = db.execute(
                text("""
                    SELECT momentum_20d, volatility_20d, turnover_avg_20d, composite_score
                    FROM stock_factors
                    WHERE ts_code = :code
                    ORDER BY trade_date DESC LIMIT 1
                """),
                {"code": ts_code},
            ).fetchone()

            if factor:
                results["momentum_20d"] = float(factor[0]) if factor[0] else None
                results["volatility_20d"] = float(factor[1]) if factor[1] else None
                results["composite_score"] = float(factor[3]) if factor[3] else None

    except Exception as e:
        logger.error(f"[stock_analysis] 技术面分析失败: {e}")
        results["technical_error"] = str(e)

    return {"technical": results}


def _step_risk(params: dict, **kwargs) -> dict:
    fundamental = kwargs.get("fundamental", {})
    technical = kwargs.get("technical", {})

    risks = []
    risk_level = "低"

    if isinstance(technical, dict):
        vol = technical.get("volatility_20d")
        if vol and vol > 3:
            risks.append(f"波动率偏高（{vol:.1f}%）")
            risk_level = "高"
        elif vol and vol > 2:
            risks.append(f"波动率中等（{vol:.1f}%）")
            if risk_level != "高":
                risk_level = "中"

        max_loss = technical.get("max_loss_20d")
        if max_loss and max_loss < -5:
            risks.append(f"20日最大跌幅 {max_loss:.1f}%")
            risk_level = "高"

        trend = technical.get("trend", "")
        if "空头" in trend:
            risks.append("均线空头排列")
            if risk_level != "高":
                risk_level = "中"

    if isinstance(fundamental, dict):
        fin_reports = fundamental.get("financial_reports", [])
        if fin_reports:
            latest_fin = fin_reports[0]
            net_profit = latest_fin.get("net_profit")
            if net_profit and net_profit < 0:
                risks.append("最近财报净利润为负")
                risk_level = "高"

    if not risks:
        risks.append("未发现明显风险信号")

    return {
        "risk": {
            "level": risk_level,
            "items": risks,
        }
    }


def _step_synthesize(params: dict, **kwargs) -> dict:
    fundamental = kwargs.get("fundamental", {})
    technical = kwargs.get("technical", {})
    risk = kwargs.get("risk", {})

    ts_code = params.get("ts_code", "未知")
    name = fundamental.get("name", "") if isinstance(fundamental, dict) else ""
    industry = fundamental.get("industry", "") if isinstance(fundamental, dict) else ""

    lines = []
    lines.append(f"# {name}（{ts_code}）综合分析报告")
    lines.append(f"行业: {industry}")
    lines.append("")

    if isinstance(fundamental, dict) and fundamental.get("latest_close"):
        lines.append("## 基本面概况")
        lines.append(f"- 最新收盘价: {fundamental.get('latest_close')}")
        lines.append(f"- 最新涨跌幅: {fundamental.get('latest_pct_chg', 0)}%")
        if fundamental.get("ma5"):
            lines.append(f"- 5日均线: {fundamental.get('ma5')}")
        if fundamental.get("ma20"):
            lines.append(f"- 20日均线: {fundamental.get('ma20')}")
        if fundamental.get("avg_pct_20d") is not None:
            lines.append(f"- 20日平均涨跌幅: {fundamental.get('avg_pct_20d')}%")
        fin = fundamental.get("financial_reports", [])
        if fin:
            latest = fin[0]
            lines.append(f"- 最新财报期: {latest.get('end_date')}")
            if latest.get("roe"):
                lines.append(f"- ROE: {latest.get('roe')}%")
            if latest.get("eps"):
                lines.append(f"- EPS: {latest.get('eps')}")
        lines.append("")

    if isinstance(technical, dict) and technical.get("trend"):
        lines.append("## 技术面分析")
        lines.append(f"- 趋势: {technical.get('trend')}")
        if technical.get("ma5"):
            lines.append(f"- MA5: {technical.get('ma5')} (价格在{technical.get('price_vs_ma5')})")
        if technical.get("ma20"):
            lines.append(f"- MA20: {technical.get('ma20')} (价格在{technical.get('price_vs_ma20')})")
        if technical.get("vol_signal"):
            lines.append(f"- 量能: {technical.get('vol_signal')}（量比{technical.get('vol_ratio')}）")
        if technical.get("momentum_20d") is not None:
            lines.append(f"- 20日动量: {technical.get('momentum_20d'):.2f}")
        if technical.get("composite_score") is not None:
            lines.append(f"- 综合评分: {technical.get('composite_score'):.1f}")
        lines.append("")

    if isinstance(risk, dict):
        lines.append("## 风险评估")
        lines.append(f"- 风险等级: {risk.get('level')}")
        for item in risk.get("items", []):
            lines.append(f"  - {item}")
        lines.append("")

    lines.append("⚠️ 以上分析仅供参考，不构成投资建议。投资有风险，入市需谨慎。")

    return {"report": "\n".join(lines)}


def register(registry):
    pipeline = Pipeline(
        name="stock_analysis",
        description="个股综合分析（基本面→技术面→风控→综合评级→报告）",
        params_schema={
            "type": "object",
            "properties": {
                "ts_code": {"type": "string", "description": "股票代码，如 000001.SZ"},
            },
            "required": ["ts_code"],
        },
    )

    pipeline.add_step(
        name="基本面分析",
        fn=_step_fundamental,
        outputs=["fundamental"],
    )
    pipeline.add_step(
        name="技术面分析",
        fn=_step_technical,
        outputs=["technical"],
    )
    pipeline.add_step(
        name="风险评估",
        fn=_step_risk,
        inputs=["fundamental", "technical"],
        outputs=["risk"],
    )
    pipeline.add_step(
        name="综合评级",
        fn=_step_synthesize,
        inputs=["fundamental", "technical", "risk"],
        outputs=["report"],
    )

    registry.register(pipeline)