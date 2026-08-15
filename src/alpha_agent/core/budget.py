"""Token 预算管理 - 借鉴 Hermes 的 iteration_budget 和 tool_result_storage。

Hermes 参考:
  - agent/iteration_budget.py: 迭代预算，超预算自动停止
  - tools/tool_result_storage.py: 工具结果按字符数截断，防止撑爆上下文

PG 优势:
  - 预算使用记录持久化到 PG，用于分析优化
  - 可配置的预算策略（按模型、按场景）
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from alpha_agent.utils.logger import logger


@dataclass
class BudgetConfig:
    """预算配置。"""
    max_iterations: int = 60
    max_tool_result_chars: int = 100000
    max_tool_result_chars_small_model: int = 30000
    context_window: int = 128000
    small_model_threshold: int = 65000


DEFAULT_BUDGET = BudgetConfig()


@dataclass
class IterationBudget:
    """迭代预算追踪器。

    借鉴 Hermes 的 IterationBudget:
    - 每轮 API 调用递增计数
    - 超预算自动停止并给出提示
    - 支持预算耗尽后的优雅降级

    目标导向增强:
    - extend(): 检测到有进展时智能续期
    - can_extend(): 检查最近步骤是否有新工具调用（有进展）
    - _recent_tool_names: 追踪最近调用的工具名，用于判断是否在死循环
    """
    max_iterations: int
    current: int = 0
    _exhausted: bool = False
    _warning_issued: bool = False
    _extend_count: int = 0
    _max_extends: int = 3
    _recent_tool_names: list = field(default_factory=list)

    def increment(self) -> bool:
        self.current += 1
        if self.current > self.max_iterations:
            if not self._exhausted:
                self._exhausted = True
                logger.warning(
                    f"[Budget] 迭代预算耗尽 ({self.current}/{self.max_iterations})"
                )
            return False
        return True

    def record_tool_call(self, tool_name: str) -> None:
        self._recent_tool_names.append(tool_name)
        if len(self._recent_tool_names) > 10:
            self._recent_tool_names = self._recent_tool_names[-10:]

    def can_extend(self) -> bool:
        if self._extend_count >= self._max_extends:
            return False
        recent = self._recent_tool_names[-5:] if len(self._recent_tool_names) >= 5 else self._recent_tool_names
        if len(recent) < 3:
            return True
        unique_recent = set(recent)
        if len(unique_recent) >= 2:
            return True
        return False

    def extend(self, extra_steps: int = 10) -> bool:
        if not self.can_extend():
            logger.info(
                f"[Budget] 无法续期: 最近 {min(5, len(self._recent_tool_names))} 步无新工具调用"
            )
            return False
        self.max_iterations += extra_steps
        self._exhausted = False
        self._extend_count += 1
        logger.info(
            f"[Budget] 智能续期 +{extra_steps} 步 "
            f"(新上限: {self.max_iterations}, 续期次数: {self._extend_count}/{self._max_extends})"
        )
        return True

    @property
    def remaining(self) -> int:
        return max(0, self.max_iterations - self.current)

    @property
    def exhausted(self) -> bool:
        return self._exhausted

    @property
    def usage_percent(self) -> float:
        if self.max_iterations <= 0:
            return 1.0
        return min(1.0, self.current / self.max_iterations)

    def reset(self) -> None:
        self.current = 0
        self._exhausted = False
        self._warning_issued = False


def truncate_tool_result(content: str, max_chars: int = DEFAULT_BUDGET.max_tool_result_chars) -> str:
    """截断工具结果，防止撑爆上下文窗口。

    借鉴 Hermes 的 tool_result_storage:
    - 按字符数而非 token 数截断（模型无关）
    - 保留开头和结尾，中间截断
    - 截断时给出明确的截断提示

    Args:
        content: 原始工具结果
        max_chars: 最大字符数

    Returns:
        截断后的内容
    """
    if len(content) <= max_chars:
        return content

    head_size = max_chars // 2
    tail_size = max_chars // 4
    head = content[:head_size]
    tail = content[-tail_size:]

    truncated = (
        f"{head}\n\n"
        f"... [中间 {len(content) - head_size - tail_size} 字符已截断] ...\n\n"
        f"{tail}"
    )

    logger.info(
        f"[Budget] 工具结果截断: {len(content)} -> {len(truncated)} 字符 "
        f"(限制: {max_chars})"
    )
    return truncated


def budget_for_context_window(context_length: int) -> BudgetConfig:
    """根据上下文窗口大小计算合适的预算配置。

    借鉴 Hermes 的 budget_for_context_window:
    - 大窗口模型使用宽松预算
    - 小窗口模型使用紧缩预算
    """
    if context_length >= 200000:
        return BudgetConfig(
            max_iterations=50,
            max_tool_result_chars=200000,
            context_window=context_length,
        )
    elif context_length >= 100000:
        return BudgetConfig(
            max_iterations=30,
            max_tool_result_chars=100000,
            context_window=context_length,
        )
    else:
        return BudgetConfig(
            max_iterations=15,
            max_tool_result_chars=30000,
            context_window=context_length,
            small_model_threshold=context_length,
        )


def estimate_tokens_rough(text: str) -> int:
    """粗略估算 token 数。"""
    import re
    if not text:
        return 0
    chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
    other = len(text) - chinese
    return int(chinese / 1.5 + other / 4)


def estimate_messages_tokens_rough(messages: List[Dict[str, Any]]) -> int:
    """估算消息列表的 token 数。"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens_rough(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += estimate_tokens_rough(part.get("text", ""))
        total += 4
    return total