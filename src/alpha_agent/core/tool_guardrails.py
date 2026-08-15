"""精细化工具调用护栏。

核心改进：
  1. 幂等/变异工具分类 —— 区分只读工具和修改工具
  2. 精确失败检测 —— 相同参数+相同失败 → 阻断
  3. 同工具失败追踪 —— 不同参数但同工具连续失败 → 警告
  4. 无进展检测 —— 幂等工具返回相同结果 → 警告/阻断
  5. 结果哈希 —— 结构化结果比较，避免字符串误判
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from alpha_agent.utils.logger import logger


# ============================================================================
# 工具分类: 幂等 vs 变异
# ============================================================================

IDEMPOTENT_TOOL_NAMES = frozenset({
    "get_database_schema",
    "web_search",
    "get_current_time",
    "get_stock_info",
    "get_kline_data",
    "get_market_overview",
    "get_macro_data",
    "get_news",
    "get_monitor",
    "get_portfolio",
    "generate_chart",
    "detect_anomalies",
    "attribute_analysis",
    "manage_alerts",
    "remember",
    "get_comparison",
    "get_insight",
    "get_knowledge_graph",
    "process",
})

MUTATING_TOOL_NAMES = frozenset({
    "terminal",
    "execute_code",
    "execute_pipeline",
    "skill_manage",
    "delegate_task",
    "backtest",
    "factor_backtest",
    "screener",
    "data_sync",
})


# ============================================================================
# 数据模型
# ============================================================================

@dataclass(frozen=True)
class ToolCallSignature:
    """工具调用的唯一签名: tool_name + 规范化 args JSON。"""
    tool_name: str
    args_hash: str

    @classmethod
    def from_call(cls, tool_name: str, args: Mapping[str, Any]) -> "ToolCallSignature":
        try:
            args_str = json.dumps(
                args,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        except (TypeError, ValueError):
            args_str = str(args)
        return cls(
            tool_name=tool_name,
            args_hash=hashlib.sha256(args_str.encode("utf-8")).hexdigest(),
        )


@dataclass(frozen=True)
class ToolGuardrailDecision:
    """护栏决策结果。"""
    action: str = "allow"
    code: str = ""
    message: str = ""
    tool_name: str = ""
    count: int = 0
    signature: ToolCallSignature | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "code": self.code,
            "tool_name": self.tool_name,
            "count": self.count,
        }


@dataclass
class ToolCallGuardrailConfig:
    """护栏配置阈值。

    warnings_enabled: 是否启用警告（默认 True）
    hard_stop_enabled: 是否启用硬阻断（默认 False，交互式场景只警告不阻断）
    exact_failure_warn_after: 精确失败多少次后警告
    exact_failure_block_after: 精确失败多少次后阻断
    same_tool_failure_warn_after: 同工具失败多少次后警告
    same_tool_failure_halt_after: 同工具失败多少次后强制停止
    no_progress_warn_after: 幂等工具无进展多少次后警告
    no_progress_block_after: 幂等工具无进展多少次后阻断
    """
    warnings_enabled: bool = True
    hard_stop_enabled: bool = False
    exact_failure_warn_after: int = 2
    exact_failure_block_after: int = 5
    same_tool_failure_warn_after: int = 3
    same_tool_failure_halt_after: int = 8
    no_progress_warn_after: int = 2
    no_progress_block_after: int = 5
    idempotent_tools: frozenset[str] = field(default_factory=lambda: IDEMPOTENT_TOOL_NAMES)
    mutating_tools: frozenset[str] = field(default_factory=lambda: MUTATING_TOOL_NAMES)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "ToolCallGuardrailConfig":
        if not isinstance(data, Mapping):
            return cls()

        warn_after = data.get("warn_after", {}) or {}
        hard_stop_after = data.get("hard_stop_after", {}) or {}

        defaults = cls()
        return cls(
            warnings_enabled=_as_bool(data.get("warnings_enabled"), defaults.warnings_enabled),
            hard_stop_enabled=_as_bool(data.get("hard_stop_enabled"), defaults.hard_stop_enabled),
            exact_failure_warn_after=_positive_int(
                warn_after.get("exact_failure"), defaults.exact_failure_warn_after
            ),
            exact_failure_block_after=_positive_int(
                hard_stop_after.get("exact_failure"), defaults.exact_failure_block_after
            ),
            same_tool_failure_warn_after=_positive_int(
                warn_after.get("same_tool_failure"), defaults.same_tool_failure_warn_after
            ),
            same_tool_failure_halt_after=_positive_int(
                hard_stop_after.get("same_tool_failure"), defaults.same_tool_failure_halt_after
            ),
            no_progress_warn_after=_positive_int(
                warn_after.get("no_progress"), defaults.no_progress_warn_after
            ),
            no_progress_block_after=_positive_int(
                hard_stop_after.get("no_progress"), defaults.no_progress_block_after
            ),
        )


# ============================================================================
# 工具失败分类器
# ============================================================================

def classify_tool_failure(tool_name: str, result: str | None) -> tuple[bool, str]:
    """判断工具调用是否失败。

    _detect_tool_failure 逻辑，按工具类型做精确判断。
    返回 (is_failure, failure_tag)。
    """
    if result is None:
        return False, ""

    if tool_name == "terminal":
        data = _safe_json_loads(result)
        if isinstance(data, dict):
            exit_code = data.get("exit_code")
            if exit_code is not None and exit_code != 0:
                return True, f" [exit {exit_code}]"
            stderr = data.get("stderr", "")
            if stderr and "Error" in stderr:
                return True, " [stderr error]"
        return False, ""

    if tool_name == "execute_code":
        data = _safe_json_loads(result)
        if isinstance(data, dict):
            if data.get("success") is False:
                return True, " [execute failed]"
            if data.get("error"):
                return True, " [error]"
        return False, ""

    if tool_name == "execute_pipeline":
        data = _safe_json_loads(result)
        if isinstance(data, dict):
            if data.get("status") == "failed":
                return True, " [pipeline failed]"
        return False, ""

    lower = result[:500].lower()
    if '"error"' in lower or '"failed"' in lower:
        return True, " [error]"

    failure_markers = ["失败", "不可用", "认证失败", "API Key", "暂时不可用"]
    for marker in failure_markers:
        if marker in result:
            return True, f" [{marker}]"

    return False, ""


# ============================================================================
# 护栏控制器
# ============================================================================

class ToolCallGuardrailController:
    """精细化工具调用护栏控制器。

    每轮对话（per-turn）创建新实例，追踪该轮内的工具调用模式。
    ToolCallGuardrailController，支持：
      - 精确失败追踪（相同参数+相同失败）
      - 同工具失败追踪（不同参数但同工具）
      - 无进展追踪（幂等工具返回相同结果）
    """

    def __init__(self, config: ToolCallGuardrailConfig | None = None):
        self.config = config or ToolCallGuardrailConfig()
        self.reset_for_turn()

    def reset_for_turn(self) -> None:
        self._exact_failure_counts: dict[ToolCallSignature, int] = {}
        self._same_tool_failure_counts: dict[str, int] = {}
        self._no_progress: dict[ToolCallSignature, tuple[str, int]] = {}
        self._halt_decision: ToolGuardrailDecision | None = None

    @property
    def halt_decision(self) -> ToolGuardrailDecision | None:
        return self._halt_decision

    @property
    def has_blocked_tools(self) -> bool:
        return self._halt_decision is not None

    def is_tool_blocked(self, tool_name: str) -> bool:
        if self._halt_decision is not None:
            if self._halt_decision.tool_name == tool_name:
                return True
            if tool_name in ("process",):
                return False
            return True
        return False

    def _is_idempotent(self, tool_name: str) -> bool:
        if tool_name in self.config.mutating_tools:
            return False
        return tool_name in self.config.idempotent_tools

    def before_call(
        self, tool_name: str, args: Mapping[str, Any] | None
    ) -> ToolGuardrailDecision:
        """工具调用前的护栏检查。

        在 LLM 决定调用工具后、实际执行前调用。
        如果 hard_stop_enabled，可能直接阻断工具调用。
        """
        args = _coerce_args(args)
        signature = ToolCallSignature.from_call(tool_name, args)

        if not self.config.hard_stop_enabled:
            return ToolGuardrailDecision(tool_name=tool_name, signature=signature)

        exact_count = self._exact_failure_counts.get(signature, 0)
        if exact_count >= self.config.exact_failure_block_after:
            decision = ToolGuardrailDecision(
                action="block",
                code="repeated_exact_failure_block",
                message=(
                    f"Blocked {tool_name}: 相同参数已失败 {exact_count} 次。"
                    "请停止重试，换策略或说明障碍。"
                ),
                tool_name=tool_name,
                count=exact_count,
                signature=signature,
            )
            self._halt_decision = decision
            return decision

        if self._is_idempotent(tool_name):
            record = self._no_progress.get(signature)
            if record is not None:
                _result_hash, repeat_count = record
                if repeat_count >= self.config.no_progress_block_after:
                    decision = ToolGuardrailDecision(
                        action="block",
                        code="idempotent_no_progress_block",
                        message=(
                            f"Blocked {tool_name}: 此只读调用已返回相同结果 "
                            f"{repeat_count} 次。请使用已有结果或换查询。"
                        ),
                        tool_name=tool_name,
                        count=repeat_count,
                        signature=signature,
                    )
                    self._halt_decision = decision
                    return decision

        return ToolGuardrailDecision(tool_name=tool_name, signature=signature)

    def after_call(
        self,
        tool_name: str,
        args: Mapping[str, Any] | None,
        result: str | None,
        *,
        failed: bool | None = None,
    ) -> ToolGuardrailDecision:
        """工具调用后的护栏检查。

        在工具执行完成后调用，记录结果并检测模式。
        """
        args = _coerce_args(args)
        signature = ToolCallSignature.from_call(tool_name, args)

        if failed is None:
            failed, _ = classify_tool_failure(tool_name, result)

        if failed:
            exact_count = self._exact_failure_counts.get(signature, 0) + 1
            self._exact_failure_counts[signature] = exact_count

            same_count = self._same_tool_failure_counts.get(tool_name, 0) + 1
            self._same_tool_failure_counts[tool_name] = same_count

            if self.config.hard_stop_enabled:
                if exact_count >= self.config.exact_failure_block_after:
                    return ToolGuardrailDecision(
                        action="halt",
                        code="exact_failure_halt",
                        message=_tool_failure_recovery_hint(tool_name, exact_count),
                        tool_name=tool_name,
                        count=exact_count,
                        signature=signature,
                    )
                if same_count >= self.config.same_tool_failure_halt_after:
                    return ToolGuardrailDecision(
                        action="halt",
                        code="same_tool_failure_halt",
                        message=_tool_failure_recovery_hint(tool_name, same_count),
                        tool_name=tool_name,
                        count=same_count,
                        signature=signature,
                    )

            if self.config.warnings_enabled:
                if exact_count >= self.config.exact_failure_warn_after:
                    return ToolGuardrailDecision(
                        action="warn",
                        code="exact_failure_warning",
                        message=_tool_failure_recovery_hint(tool_name, exact_count),
                        tool_name=tool_name,
                        count=exact_count,
                        signature=signature,
                    )
                if same_count >= self.config.same_tool_failure_warn_after:
                    return ToolGuardrailDecision(
                        action="warn",
                        code="same_tool_failure_warning",
                        message=_tool_failure_recovery_hint(tool_name, same_count),
                        tool_name=tool_name,
                        count=same_count,
                        signature=signature,
                    )

            return ToolGuardrailDecision(
                tool_name=tool_name, count=exact_count, signature=signature
            )

        self._exact_failure_counts.pop(signature, None)
        self._same_tool_failure_counts.pop(tool_name, None)

        if not self._is_idempotent(tool_name):
            self._no_progress.pop(signature, None)
            return ToolGuardrailDecision(tool_name=tool_name, signature=signature)

        result_hash = _result_hash(result)
        previous = self._no_progress.get(signature)
        repeat_count = 1
        if previous is not None and previous[0] == result_hash:
            repeat_count = previous[1] + 1
        self._no_progress[signature] = (result_hash, repeat_count)

        if self.config.warnings_enabled and repeat_count >= self.config.no_progress_warn_after:
            return ToolGuardrailDecision(
                action="warn",
                code="idempotent_no_progress_warning",
                message=(
                    f"{tool_name} 返回了相同结果 {repeat_count} 次。"
                    "请使用已提供的结果，或改变查询而不是重复不变调用。"
                ),
                tool_name=tool_name,
                count=repeat_count,
                signature=signature,
            )

        return ToolGuardrailDecision(
            tool_name=tool_name, count=repeat_count, signature=signature
        )


def toolguard_synthetic_result(decision: ToolGuardrailDecision) -> str:
    """为被阻断的工具调用生成合成结果。"""
    return json.dumps(
        {
            "error": decision.message,
            "guardrail": decision.to_metadata(),
        },
        ensure_ascii=False,
    )


def append_toolguard_guidance(result: str, decision: ToolGuardrailDecision) -> str:
    """在工具结果末尾追加护栏指引。"""
    if decision.action not in {"warn", "halt"} or not decision.message:
        return result
    label = "工具循环硬停止" if decision.action == "halt" else "工具循环警告"
    suffix = (
        f"\n\n[{label}: "
        f"{decision.code}; count={decision.count}; {decision.message}]"
    )
    return (result or "") + suffix


# ============================================================================
# 辅助函数
# ============================================================================

def _tool_failure_recovery_hint(tool_name: str, count: int) -> str:
    """面向 LLM 的恢复提示。"""
    common = (
        f"{tool_name} 本轮已失败 {count} 次。这看起来像循环。"
        "不要切换到纯文本回复；继续使用工具，但先诊断再重试。"
        "首先检查最新的错误/输出并验证你的假设。"
    )
    if tool_name == "terminal":
        return common + (
            "对于 terminal 失败，先运行诊断命令如 `pwd && ls -la`，"
            "然后尝试绝对路径、更简单的命令、不同的工作目录或其他工具。"
        )
    return common + (
        "尝试不同的参数、更窄的查询/路径、相关时使用绝对路径，"
        "或使用其他能取得进展的工具。如果障碍是外部因素，"
        "在诊断一次后报告障碍，而不是重复相同的失败路径。"
    )


def _coerce_args(args: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return args if isinstance(args, Mapping) else {}


def _result_hash(result: str | None) -> str:
    """对工具结果做结构化哈希，用于检测无进展调用。"""
    parsed = _safe_json_loads(result or "")
    if parsed is not None:
        try:
            canonical = json.dumps(
                parsed,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        except TypeError:
            canonical = str(parsed)
    else:
        canonical = result or ""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_json_loads(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on", "enabled"}:
            return True
        if lowered in {"0", "false", "no", "off", "disabled"}:
            return False
    return default


def _positive_int(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 1 else default