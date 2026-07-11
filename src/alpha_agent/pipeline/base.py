"""Pipeline 基础框架 —— 定义 Pipeline、Step、Result 数据结构。"""
from typing import Dict, Any, List, Optional, Callable, Protocol, runtime_checkable
from dataclasses import dataclass, field
from enum import Enum

from alpha_agent.utils.logger import logger


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@runtime_checkable
class StepFn(Protocol):
    def __call__(self, *, params: dict, **kwargs: Any) -> Optional[dict]: ...


StepFnLike = Callable[..., Optional[dict]]


@dataclass
class StepResult:
    step_name: str
    status: StepStatus = StepStatus.COMPLETED
    outputs: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: float = 0


@dataclass
class PipelineResult:
    pipeline_name: str
    status: str = "completed"
    steps: List[StepResult] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    total_duration_ms: float = 0

    def to_text(self) -> str:
        parts = [f"Pipeline: {self.pipeline_name} [{self.status}]"]
        parts.append(f"总耗时: {self.total_duration_ms / 1000:.1f}s")
        parts.append("")

        for step in self.steps:
            emoji = {
                StepStatus.COMPLETED: "✅",
                StepStatus.FAILED: "❌",
                StepStatus.SKIPPED: "⏭️",
                StepStatus.RUNNING: "🔄",
                StepStatus.PENDING: "⏳",
            }.get(step.status, "❓")
            parts.append(f"  {emoji} {step.step_name} ({step.duration_ms:.0f}ms)")
            if step.error:
                parts.append(f"     错误: {step.error}")

        if self.data:
            parts.append("")
            parts.append("--- 结果 ---")
            for key, value in self.data.items():
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, dict):
                    for k, v in value.items():
                        parts.append(f"{k}: {v}")
                else:
                    parts.append(str(value))

        return "\n".join(parts)


class PipelineStep:
    def __init__(
        self,
        name: str,
        fn: StepFnLike,
        inputs: Optional[List[str]] = None,
        outputs: Optional[List[str]] = None,
        optional: bool = False,
    ):
        self.name = name
        self.fn = fn
        self.inputs = inputs or []
        self.outputs = outputs or []
        self.optional = optional

    def execute(self, params: dict, context: Dict[str, Any]) -> StepResult:
        import time
        start = time.time()

        try:
            step_kwargs: Dict[str, Any] = {}
            for key in self.inputs:
                if key in context:
                    step_kwargs[key] = context[key]
                elif key in params:
                    step_kwargs[key] = params[key]

            result = self.fn(params=params, **step_kwargs)

            duration = (time.time() - start) * 1000

            if result is None:
                return StepResult(
                    step_name=self.name,
                    status=StepStatus.COMPLETED,
                    duration_ms=duration,
                )

            if isinstance(result, dict):
                return StepResult(
                    step_name=self.name,
                    status=StepStatus.COMPLETED,
                    outputs=result,
                    duration_ms=duration,
                )

            return StepResult(
                step_name=self.name,
                status=StepStatus.COMPLETED,
                outputs={"result": result},
                duration_ms=duration,
            )

        except Exception as e:
            duration = (time.time() - start) * 1000
            if self.optional:
                logger.warning(f"[Pipeline] 可选步骤 {self.name} 失败（已跳过）: {e}")
                return StepResult(
                    step_name=self.name,
                    status=StepStatus.SKIPPED,
                    error=str(e),
                    duration_ms=duration,
                )
            logger.error(f"[Pipeline] 步骤 {self.name} 失败: {e}")
            return StepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=str(e),
                duration_ms=duration,
            )


class Pipeline:
    def __init__(
        self,
        name: str,
        description: str,
        params_schema: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.description = description
        self.params_schema = params_schema or {}
        self._steps: List[PipelineStep] = []

    def add_step(
        self,
        name: str,
        fn: StepFnLike,
        inputs: Optional[List[str]] = None,
        outputs: Optional[List[str]] = None,
        optional: bool = False,
    ) -> "Pipeline":
        step = PipelineStep(
            name=name,
            fn=fn,
            inputs=inputs,
            outputs=outputs,
            optional=optional,
        )
        self._steps.append(step)
        return self

    def execute(
        self,
        params: Optional[Dict[str, Any]] = None,
        progress_cb: Optional[Callable[[str, int, int], None]] = None,
    ) -> PipelineResult:
        import time
        total_start = time.time()
        params = params or {}
        context: Dict[str, Any] = {}
        step_results: List[StepResult] = []
        failed = False

        for i, step in enumerate(self._steps):
            if progress_cb:
                progress_cb(step.name, i + 1, len(self._steps))

            logger.info(f"[Pipeline:{self.name}] 执行步骤 {i+1}/{len(self._steps)}: {step.name}")

            step_result = step.execute(params, context)
            step_results.append(step_result)

            if step_result.status == StepStatus.COMPLETED:
                context.update(step_result.outputs)
            elif step_result.status == StepStatus.FAILED:
                failed = True
                break

        total_duration = (time.time() - total_start) * 1000

        result = PipelineResult(
            pipeline_name=self.name,
            status="failed" if failed else "completed",
            steps=step_results,
            data=context,
            total_duration_ms=total_duration,
        )

        if failed:
            last_failed = next(
                (s for s in reversed(step_results) if s.status == StepStatus.FAILED),
                None,
            )
            result.error = last_failed.error if last_failed else "Unknown error"

        logger.info(
            f"[Pipeline:{self.name}] 执行完成 "
            f"({result.status}, {total_duration / 1000:.1f}s, "
            f"{len(step_results)}/{len(self._steps)} 步骤)"
        )

        return result