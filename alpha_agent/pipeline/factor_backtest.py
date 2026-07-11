"""factor_backtest Pipeline —— 因子回测 Pipeline。

选股 → 因子构建 → 回测 → 绩效评估
"""
from alpha_agent.pipeline.base import Pipeline
from alpha_agent.utils.logger import logger


def _step_select_universe(params: dict, **kwargs) -> dict:
    from alpha_agent.infra.db.database import SessionLocal
    from sqlalchemy import text

    try:
        with SessionLocal() as db:
            rows = db.execute(
                text("SELECT ts_code, name, industry FROM stocks WHERE is_active = true ORDER BY ts_code")
            ).fetchall()

            pool = [{"ts_code": r[0], "name": r[1], "industry": r[2] or ""} for r in rows]
            return {"universe": pool, "count": len(pool)}
    except Exception as e:
        logger.error(f"[factor_backtest] 选股失败: {e}")
        return {"universe": [], "count": 0, "error": str(e)}


def _step_build_factor(params: dict, universe: list = None, **kwargs) -> dict:
    from alpha_agent.infra.db.database import SessionLocal
    from sqlalchemy import text

    factor_name = params.get("factor", "composite_score")
    top_n = params.get("top_n", 20)

    try:
        with SessionLocal() as db:
            if factor_name == "composite_score":
                rows = db.execute(
                    text("""
                        SELECT ts_code, composite_score, momentum_20d, volatility_20d, rsi_14
                        FROM stock_factors
                        WHERE composite_score IS NOT NULL
                        ORDER BY composite_score DESC
                        LIMIT :limit
                    """),
                    {"limit": max(top_n * 3, 50)},
                ).fetchall()

                results = []
                for r in rows:
                    results.append({
                        "ts_code": r[0],
                        "composite_score": float(r[1]) if r[1] else 0,
                        "momentum_20d": float(r[2]) if r[2] else 0,
                        "volatility_20d": float(r[3]) if r[3] else 0,
                        "rsi_14": float(r[4]) if r[4] else 0,
                    })
                return {"portfolio": results[:top_n], "factor": factor_name, "count": len(results)}
            elif factor_name == "momentum":
                rows = db.execute(
                    text("""
                        SELECT ts_code, momentum_20d, composite_score
                        FROM stock_factors
                        WHERE momentum_20d IS NOT NULL
                        ORDER BY momentum_20d DESC
                        LIMIT :limit
                    """),
                    {"limit": top_n},
                ).fetchall()
                results = [
                    {"ts_code": r[0], "momentum_20d": float(r[1]), "composite_score": float(r[2]) if r[2] else 0}
                    for r in rows
                ]
                return {"portfolio": results, "factor": factor_name, "count": len(results)}
            else:
                return {"portfolio": [], "factor": factor_name, "error": f"未知因子: {factor_name}"}
    except Exception as e:
        logger.error(f"[factor_backtest] 因子构建失败: {e}")
        return {"portfolio": [], "error": str(e)}


def _step_run_backtest(params: dict, portfolio: list = None, **kwargs) -> dict:
    from alpha_agent.infra.db.database import SessionLocal
    from sqlalchemy import text

    if not portfolio:
        return {"backtest": {}, "error": "无持仓数据"}

    lookback = params.get("lookback_days", 60)
    ts_codes = [p["ts_code"] for p in portfolio[:10]]

    try:
        with SessionLocal() as db:
            rows = db.execute(
                text("""
                    SELECT ts_code, AVG(pct_chg) as avg_return,
                           MAX(pct_chg) as max_return, MIN(pct_chg) as min_return,
                           STDDEV(pct_chg) as volatility
                    FROM daily_kline
                    WHERE ts_code IN :codes
                      AND trade_date >= (SELECT MAX(trade_date) FROM daily_kline) - :lookback
                    GROUP BY ts_code
                """),
                {"codes": tuple(ts_codes), "lookback": lookback},
            ).fetchall()

            results = []
            avg_returns = []
            for r in rows:
                avg_returns.append(float(r[1]) if r[1] else 0)
                results.append({
                    "ts_code": r[0],
                    "avg_return": float(r[1]) if r[1] else 0,
                    "max_return": float(r[2]) if r[2] else 0,
                    "min_return": float(r[3]) if r[3] else 0,
                    "volatility": float(r[4]) if r[4] else 0,
                })

            portfolio_return = sum(avg_returns) / len(avg_returns) if avg_returns else 0
            return {
                "backtest": {
                    "results": results,
                    "portfolio_avg_return": round(portfolio_return, 2),
                    "lookback_days": lookback,
                    "stock_count": len(results),
                }
            }
    except Exception as e:
        logger.error(f"[factor_backtest] 回测失败: {e}")
        return {"backtest": {}, "error": str(e)}


def _step_evaluate_performance(params: dict, backtest: dict = None, **kwargs) -> dict:
    if not backtest or not backtest.get("results"):
        return {"text": "无回测数据"}

    results = backtest["results"]
    if not results:
        return {"text": "回测结果为空"}

    avg_ret = backtest.get("portfolio_avg_return", 0)
    volatilities = [r["volatility"] for r in results if r.get("volatility")]

    avg_vol = sum(volatilities) / len(volatilities) if volatilities else 0
    sharpe = (avg_ret / avg_vol) if avg_vol > 0 else 0
    max_dd = min(r.get("min_return", 0) for r in results)

    lines = [
        f"## 因子回测绩效评估\n",
        f"回测股票数: {backtest.get('stock_count', 0)}",
        f"回测区间: {backtest.get('lookback_days', 60)} 天",
        f"组合平均日收益: {avg_ret:.2f}%",
        f"平均波动率: {avg_vol:.2f}%",
        f"夏普比率(近似): {sharpe:.2f}",
        f"最大回撤: {max_dd:.2f}%",
        "",
        "## 持仓明细",
    ]
    for r in results:
        lines.append(
            f"  {r['ts_code']} | 日均收益: {r['avg_return']:+.2f}% "
            f"| 波动率: {r['volatility']:.2f}% | 最大回撤: {r['min_return']:.2f}%"
        )

    return {"text": "\n".join(lines)}


def register(registry):
    pipeline = Pipeline(
        name="factor_backtest",
        description="因子回测 Pipeline：选股 → 因子构建 → 回测 → 绩效评估",
        params_schema={
            "factor": {"type": "str", "default": "composite_score", "description": "因子名称"},
            "top_n": {"type": "int", "default": 20, "description": "持仓股票数"},
            "lookback_days": {"type": "int", "default": 60, "description": "回测天数"},
        },
    )
    pipeline.add_step("select_universe", _step_select_universe)
    pipeline.add_step("build_factor", _step_build_factor, inputs=["universe"])
    pipeline.add_step("run_backtest", _step_run_backtest, inputs=["portfolio"])
    pipeline.add_step("evaluate_performance", _step_evaluate_performance, inputs=["backtest"])
    registry.register(pipeline)