"""Pipeline 模块 —— 可组合的分析步骤编排。

Pipelines:
  - stock_analysis: 个股综合分析
  - market_overview: 市场概览
  - data_health_check: 数据健康检查
  - stock_screening: 选股 Pipeline
  - factor_backtest: 因子回测 Pipeline
  - portfolio_build: 组合构建 Pipeline
  - data_auto_repair: 数据自动修复 Pipeline

Utilities:
  - db_utils: 统一的 DB 会话管理，消除 Pipeline 步骤中的重复代码
"""
from alpha_agent.pipeline.base import Pipeline, PipelineStep, PipelineResult
from alpha_agent.pipeline.registry import PipelineRegistry, get_pipeline_registry

__all__ = [
    "Pipeline",
    "PipelineStep",
    "PipelineResult",
    "PipelineRegistry",
    "get_pipeline_registry",
]