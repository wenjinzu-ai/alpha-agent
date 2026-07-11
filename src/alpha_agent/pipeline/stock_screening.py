"""stock_screening Pipeline —— 选股 Pipeline。

获取标的池 → 因子计算 → 排名筛选 → 输出
"""
from alpha_agent.pipeline.base import Pipeline
from alpha_agent.utils.logger import logger


def _step_get_pool(params: dict, **kwargs) -> dict:
    from alpha_agent.infra.db.database import SessionLocal
    from sqlalchemy import text

    try:
        with SessionLocal() as db:
            rows = db.execute(
                text("SELECT ts_code, name, industry FROM stocks WHERE is_active = true ORDER BY ts_code")
            ).fetchall()

            pool = [{"ts_code": r[0], "name": r[1], "industry": r[2] or ""} for r in rows]
            return {"pool": pool, "pool_size": len(pool)}
    except Exception as e:
        logger.error(f"[stock_screening] 获取标的池失败: {e}")
        return {"pool": [], "pool_size": 0, "error": str(e)}


def _step_calc_factors(params: dict, pool: list = None, **kwargs) -> dict:
    from alpha_agent.infra.db.database import SessionLocal
    from sqlalchemy import text

    if not pool:
        return {"factors": [], "error": "标的池为空"}

    min_score = params.get("min_score", 50)
    limit = params.get("limit", 20)

    try:
        with SessionLocal() as db:
            rows = db.execute(
                text("""
                    SELECT ts_code, composite_score
                    FROM stock_factors
                    WHERE composite_score >= :min_score
                    ORDER BY composite_score DESC
                    LIMIT :limit
                """),
                {"min_score": min_score, "limit": limit},
            ).fetchall()

            factors = [{"ts_code": r[0], "composite_score": float(r[1])} for r in rows]
            return {"factors": factors, "factor_count": len(factors)}
    except Exception as e:
        logger.error(f"[stock_screening] 因子计算失败: {e}")
        return {"factors": [], "error": str(e)}


def _step_rank_filter(params: dict, factors: list = None, pool: list = None, **kwargs) -> dict:
    if not factors:
        return {"ranked": [], "error": "无因子数据"}

    ranked = sorted(factors, key=lambda x: x.get("composite_score", 0), reverse=True)
    top_n = params.get("top_n", 10)
    top = ranked[:top_n]

    pool_map = {s["ts_code"]: s for s in (pool or [])}
    result = []
    for item in top:
        code = item["ts_code"]
        stock_info = pool_map.get(code, {})
        result.append({
            "ts_code": code,
            "name": stock_info.get("name", ""),
            "industry": stock_info.get("industry", ""),
            "composite_score": item["composite_score"],
        })

    return {"ranked": result, "top_n": top_n, "total_candidates": len(ranked)}


def _step_output(params: dict, ranked: list = None, **kwargs) -> dict:
    if not ranked:
        return {"text": "未找到符合条件的股票"}

    lines = [f"## 选股结果（Top {len(ranked)}）\n"]
    for i, s in enumerate(ranked, 1):
        lines.append(
            f"{i}. {s['ts_code']} {s['name']} [{s['industry']}] "
            f"综合评分: {s['composite_score']:.1f}"
        )
    return {"text": "\n".join(lines)}


def register(registry):
    pipeline = Pipeline(
        name="stock_screening",
        description="选股 Pipeline：获取标的池 → 因子计算 → 排名筛选 → 输出",
        params_schema={
            "min_score": {"type": "int", "default": 50, "description": "最低综合评分"},
            "top_n": {"type": "int", "default": 10, "description": "返回前N只"},
            "limit": {"type": "int", "default": 50, "description": "因子查询上限"},
        },
    )
    pipeline.add_step("get_pool", _step_get_pool)
    pipeline.add_step("calc_factors", _step_calc_factors, inputs=["pool"])
    pipeline.add_step("rank_filter", _step_rank_filter, inputs=["factors", "pool"])
    pipeline.add_step("output", _step_output, inputs=["ranked"])
    registry.register(pipeline)