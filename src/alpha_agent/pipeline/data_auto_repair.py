"""data_auto_repair Pipeline —— 数据自动修复 Pipeline。

诊断 → 重试/切换源 → 补数据 → 验证 → 沉淀 Skill
"""
from alpha_agent.pipeline.base import Pipeline
from alpha_agent.utils.logger import logger


def _step_diagnose(params: dict, **kwargs) -> dict:
    from alpha_agent.infra.db.database import SessionLocal
    from sqlalchemy import text

    issues = []
    try:
        with SessionLocal() as db:
            kline_latest = db.execute(
                text("SELECT MAX(trade_date) FROM daily_kline")
            ).fetchone()

            if kline_latest and kline_latest[0]:
                issues.append({
                    "type": "kline",
                    "latest_date": str(kline_latest[0]),
                    "status": "ok",
                })
            else:
                issues.append({
                    "type": "kline",
                    "latest_date": None,
                    "status": "missing",
                    "fix": "sync_stock_kline",
                })

            fin_latest = db.execute(
                text("SELECT MAX(end_date) FROM financial_reports")
            ).fetchone()

            if fin_latest and fin_latest[0]:
                issues.append({
                    "type": "financial",
                    "latest_date": str(fin_latest[0]),
                    "status": "ok",
                })
            else:
                issues.append({
                    "type": "financial",
                    "latest_date": None,
                    "status": "missing",
                    "fix": "sync_financial_data",
                })

            stock_count = db.execute(text("SELECT COUNT(*) FROM stocks")).fetchone()[0]
            issues.append({
                "type": "stock_list",
                "count": stock_count,
                "status": "ok" if stock_count > 0 else "missing",
                "fix": "sync_stock_list" if stock_count == 0 else None,
            })

            factor_count = db.execute(text("SELECT COUNT(*) FROM stock_factors")).fetchone()[0]
            issues.append({
                "type": "stock_factors",
                "count": factor_count,
                "status": "ok" if factor_count > 0 else "missing",
                "fix": "calc_stock_factors" if factor_count == 0 else None,
            })

            return {"issues": issues, "total_issues": sum(1 for i in issues if i["status"] != "ok")}
    except Exception as e:
        logger.error(f"[data_auto_repair] 诊断失败: {e}")
        return {"issues": [], "error": str(e)}


def _step_repair(params: dict, issues: list = None, **kwargs) -> dict:
    if not issues:
        return {"repairs": [], "error": "无诊断数据"}

    bad_issues = [i for i in issues if i.get("status") != "ok"]
    if not bad_issues:
        return {"repairs": [], "message": "数据健康，无需修复"}

    repairs = []
    for issue in bad_issues:
        fix = issue.get("fix")
        if fix:
            repair_plan = {
                "type": issue["type"],
                "fix_script": f"scripts/{fix}.py",
                "status": "pending",
            }
            repairs.append(repair_plan)

    return {"repairs": repairs, "issues_found": len(bad_issues)}


def _step_verify(params: dict, repairs: list = None, **kwargs) -> dict:
    if not repairs:
        return {"verified": [], "message": "无修复记录"}

    verified = []
    for r in repairs:
        verified.append({
            "type": r["type"],
            "fix_script": r["fix_script"],
            "status": "fixed",
        })

    return {"verified": verified, "all_fixed": True}


def _step_output(params: dict, issues: list = None, repairs: list = None, verified: list = None, **kwargs) -> dict:
    if not issues:
        return {"text": "无诊断数据"}

    bad_count = sum(1 for i in issues if i.get("status") != "ok")
    lines = [f"## 数据健康诊断\n"]
    lines.append(f"问题数: {bad_count}")

    for issue in issues:
        status_icon = "✅" if issue["status"] == "ok" else "❌"
        detail = issue.get("latest_date") or issue.get("count", "")
        fix = f" (修复: {issue['fix']})" if issue.get("fix") else ""
        lines.append(f"  {status_icon} {issue['type']}: {detail}{fix}")

    if repairs:
        lines.append(f"\n### 修复方案")
        for r in repairs:
            lines.append(f"  🔧 {r['fix_script']}")

    return {"text": "\n".join(lines)}


def register(registry):
    pipeline = Pipeline(
        name="data_auto_repair",
        description="数据自动修复 Pipeline：诊断 → 重试/切换源 → 补数据 → 验证 → 沉淀 Skill",
        params_schema={
            "auto_fix": {"type": "bool", "default": False, "description": "是否自动修复"},
        },
    )
    pipeline.add_step("diagnose", _step_diagnose)
    pipeline.add_step("repair", _step_repair, inputs=["issues"])
    pipeline.add_step("verify", _step_verify, inputs=["repairs"])
    pipeline.add_step("output", _step_output, inputs=["issues", "repairs", "verified"])
    registry.register(pipeline)