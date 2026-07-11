"""portfolio_build Pipeline —— 组合构建 Pipeline。

选股 → 权重优化 → 风控检查 → 组合构建
"""
from alpha_agent.pipeline.base import Pipeline
from alpha_agent.utils.logger import logger


def _step_select_stocks(params: dict, **kwargs) -> dict:
    from alpha_agent.infra.db.database import SessionLocal
    from sqlalchemy import text

    min_score = params.get("min_score", 50)
    max_stocks = params.get("max_stocks", 10)

    try:
        with SessionLocal() as db:
            rows = db.execute(
                text("""
                    SELECT sf.ts_code, sf.composite_score, st.name, st.industry
                    FROM stock_factors sf
                    JOIN stocks st ON sf.ts_code = st.ts_code
                    WHERE sf.composite_score >= :min_score
                    ORDER BY sf.composite_score DESC
                    LIMIT :limit
                """),
                {"min_score": min_score, "limit": max_stocks * 2},
            ).fetchall()

            candidates = [
                {
                    "ts_code": r[0],
                    "composite_score": float(r[1]) if r[1] else 0,
                    "name": r[2],
                    "industry": r[3] or "",
                }
                for r in rows
            ]

            selected = candidates[:max_stocks]
            return {"selected": selected, "candidates": candidates, "count": len(selected)}
    except Exception as e:
        logger.error(f"[portfolio_build] 选股失败: {e}")
        return {"selected": [], "error": str(e)}


def _step_optimize_weights(params: dict, selected: list = None, **kwargs) -> dict:
    if not selected:
        return {"weights": [], "error": "无选股结果"}

    strategy = params.get("weight_strategy", "equal_weight")

    if strategy == "equal_weight":
        weight = 1.0 / len(selected)
        weights = [{"ts_code": s["ts_code"], "weight": round(weight, 4)} for s in selected]
    elif strategy == "score_weight":
        scores = [s["composite_score"] for s in selected]
        total = sum(scores)
        if total > 0:
            weights = [
                {"ts_code": s["ts_code"], "weight": round(s["composite_score"] / total, 4)}
                for s in selected
            ]
        else:
            weight = 1.0 / len(selected)
            weights = [{"ts_code": s["ts_code"], "weight": round(weight, 4)} for s in selected]
    else:
        weight = 1.0 / len(selected)
        weights = [{"ts_code": s["ts_code"], "weight": round(weight, 4)} for s in selected]

    return {"weights": weights, "strategy": strategy}


def _step_check_risk(params: dict, weights: list = None, selected: list = None, **kwargs) -> dict:
    from alpha_agent.infra.db.database import SessionLocal
    from sqlalchemy import text

    if not weights or not selected:
        return {"risk_checks": [], "passed": False, "error": "无持仓数据"}

    max_single_weight = params.get("max_single_weight", 0.3)
    max_industry_weight = params.get("max_industry_weight", 0.5)

    checks = []
    industry_weights = {}
    single_weight_pass = True
    industry_weight_pass = True

    for w in weights:
        if w["weight"] > max_single_weight:
            checks.append(f"⚠️ {w['ts_code']} 权重 {w['weight']:.1%} 超过{max_single_weight:.0%}上限")
            single_weight_pass = False

    code_to_industry = {s["ts_code"]: s.get("industry", "") for s in selected}
    for w in weights:
        industry = code_to_industry.get(w["ts_code"], "未知")
        industry_weights[industry] = industry_weights.get(industry, 0) + w["weight"]

    for ind, wgt in industry_weights.items():
        if wgt > max_industry_weight:
            checks.append(f"⚠️ 行业 {ind} 权重 {wgt:.1%} 超过{max_industry_weight:.0%}上限")
            industry_weight_pass = False

    if not checks:
        checks.append("✅ 风控检查通过")

    return {
        "risk_checks": checks,
        "passed": single_weight_pass and industry_weight_pass,
        "industry_weights": industry_weights,
        "single_weight_pass": single_weight_pass,
        "industry_weight_pass": industry_weight_pass,
    }


def _step_build_portfolio(params: dict, weights: list = None, risk_checks: list = None, **kwargs) -> dict:
    if not weights:
        return {"text": "无持仓权重"}

    lines = [f"## 组合构建结果\n"]
    lines.append(f"策略: {params.get('weight_strategy', 'equal_weight')}")
    lines.append(f"持仓数: {len(weights)}\n")
    lines.append("### 持仓明细")

    for w in weights:
        lines.append(f"  {w['ts_code']}: {w['weight']:.2%}")

    lines.append("\n### 风控检查")
    for check in (risk_checks or []):
        lines.append(f"  {check}")

    return {"text": "\n".join(lines)}


def register(registry):
    pipeline = Pipeline(
        name="portfolio_build",
        description="组合构建 Pipeline：选股 → 权重优化 → 风控检查 → 组合构建",
        params_schema={
            "min_score": {"type": "int", "default": 50, "description": "最低综合评分"},
            "max_stocks": {"type": "int", "default": 10, "description": "最大持仓数"},
            "weight_strategy": {"type": "str", "default": "equal_weight", "description": "权重策略: equal_weight/score_weight"},
            "max_single_weight": {"type": "float", "default": 0.3, "description": "单票最大权重"},
            "max_industry_weight": {"type": "float", "default": 0.5, "description": "单行业最大权重"},
        },
    )
    pipeline.add_step("select_stocks", _step_select_stocks)
    pipeline.add_step("optimize_weights", _step_optimize_weights, inputs=["selected"])
    pipeline.add_step("check_risk", _step_check_risk, inputs=["weights", "selected"])
    pipeline.add_step("build_portfolio", _step_build_portfolio, inputs=["weights", "risk_checks"])
    registry.register(pipeline)