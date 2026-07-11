"""execute_pipeline 工具 —— 一步执行预置分析工作流。

专业 Agent 的核心差异化：Hermes 没有领域 Pipeline，我们有。
后台模式走 ProcessRegistry，与 terminal 一致，可用 process 工具查询。
"""
from typing import Optional
from langchain_core.tools import tool

from alpha_agent.pipeline import get_pipeline_registry
from alpha_agent.utils.executor import write_temp_script, run_script_background, format_background_started
from alpha_agent.config import settings
from alpha_agent.utils.logger import logger


@tool
def execute_pipeline(
    pipeline: str,
    params: Optional[dict] = None,
    background: bool = False,
) -> str:
    """Execute a pre-built analysis pipeline in a single call.

    Pipelines are composable, domain-specific workflows that chain
    multiple analysis steps together. Much more efficient than calling
    individual tools one by one.

    Available pipelines:
    - stock_analysis: Full stock analysis (fundamental + technical + risk)
      params: {"ts_code": "000001.SZ"}
    - stock_screening: Stock screening (pool → factors → rank → output)
      params: {"min_score": 50, "top_n": 10}
    - factor_backtest: Factor backtest (select → factor → backtest → performance)
      params: {"factor": "composite_score", "top_n": 20}
    - portfolio_build: Portfolio construction (stocks → weights → stress test)
      params: {"top_n": 10, "risk_aversion": "moderate"}
    - market_overview: Market snapshot with anomalies
      params: {}
    - data_health_check: Check data completeness and freshness
      params: {}
    - data_auto_repair: Auto-repair data issues
      params: {"repair_mode": "auto"}

    Args:
        pipeline: Pipeline name to execute
        params: Pipeline parameters (varies by pipeline)
        background: Run in background if True. Returns task_id.
    """
    registry = get_pipeline_registry()

    if background:
        import json

        params_json = json.dumps(params or {})
        script_code = (
            "import sys\n"
            "import json\n"
            "from alpha_agent.pipeline import get_pipeline_registry\n"
            f"registry = get_pipeline_registry()\n"
            f"result = registry.execute({pipeline!r}, {params_json!s})\n"
            "print(result.get('text', str(result)))\n"
        )

        script_path = write_temp_script(script_code, prefix="pipeline")
        task_id = run_script_background(script_path, timeout=settings.pipeline_background_timeout)

        return format_background_started(task_id, "Pipeline", f"pipeline: {pipeline}")

    try:
        result = registry.execute(pipeline, params)

        status = result.get("status", "unknown")

        if status == "not_found":
            available = result.get("available", [])
            return (
                f"Pipeline '{pipeline}' 不存在\n\n"
                f"可用 Pipeline:\n"
                + "\n".join(f"  - {name}" for name in available)
            )

        if status == "failed":
            error = result.get("error", "未知错误")
            return f"Pipeline '{pipeline}' 执行失败: {error}"

        text = result.get("text", "")
        if text:
            return text

        return str(result)

    except Exception as e:
        logger.error(f"[execute_pipeline] 执行失败: {e}")
        return f"Pipeline 执行失败: {e}"