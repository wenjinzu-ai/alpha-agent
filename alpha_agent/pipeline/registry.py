"""Pipeline 注册表 —— 管理所有已注册的 Pipeline。"""
from typing import Dict, Optional, List, Any
from alpha_agent.pipeline.base import Pipeline
from alpha_agent.utils.logger import logger


class PipelineRegistry:
    def __init__(self):
        self._pipelines: Dict[str, Pipeline] = {}

    def register(self, pipeline: Pipeline):
        self._pipelines[pipeline.name] = pipeline
        logger.info(f"[PipelineRegistry] 注册 Pipeline: {pipeline.name} - {pipeline.description}")

    def get(self, name: str) -> Optional[Pipeline]:
        return self._pipelines.get(name)

    def list_pipelines(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": p.name,
                "description": p.description,
                "steps": len(p._steps),
                "params_schema": p.params_schema,
            }
            for p in self._pipelines.values()
        ]

    def execute(self, name: str, params: Optional[Dict[str, Any]] = None) -> dict:
        pipeline = self._pipelines.get(name)
        if not pipeline:
            available = list(self._pipelines.keys())
            return {
                "status": "not_found",
                "error": f"Pipeline '{name}' 不存在",
                "available": available,
            }

        try:
            result = pipeline.execute(params=params)
            return {
                "status": result.status,
                "pipeline": result.pipeline_name,
                "data": result.data,
                "steps": [
                    {
                        "name": s.step_name,
                        "status": s.status.value,
                        "duration_ms": s.duration_ms,
                        "error": s.error,
                    }
                    for s in result.steps
                ],
                "total_duration_ms": result.total_duration_ms,
                "error": result.error,
                "text": result.to_text(),
            }
        except Exception as e:
            logger.error(f"[PipelineRegistry] 执行 Pipeline {name} 失败: {e}")
            return {
                "status": "failed",
                "pipeline": name,
                "error": str(e),
            }


_registry: Optional[PipelineRegistry] = None


def get_pipeline_registry() -> PipelineRegistry:
    global _registry
    if _registry is None:
        _registry = PipelineRegistry()
        _register_default_pipelines(_registry)
    return _registry


def _register_default_pipelines(registry: PipelineRegistry):
    from alpha_agent.pipeline.stock_analysis import register as reg_sa
    from alpha_agent.pipeline.market_overview import register as reg_mo
    from alpha_agent.pipeline.data_health_check import register as reg_dhc
    from alpha_agent.pipeline.stock_screening import register as reg_ss
    from alpha_agent.pipeline.factor_backtest import register as reg_fb
    from alpha_agent.pipeline.portfolio_build import register as reg_pb
    from alpha_agent.pipeline.data_auto_repair import register as reg_dar

    reg_sa(registry)
    reg_mo(registry)
    reg_dhc(registry)
    reg_ss(registry)
    reg_fb(registry)
    reg_pb(registry)
    reg_dar(registry)

    logger.info(f"[PipelineRegistry] 默认 Pipeline 注册完成，共 {len(registry.list_pipelines())} 个")