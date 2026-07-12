"""人工交互工具 —— 借鉴 Hermes 的 clarify_tool.py。

让 LLM 主动向用户提问，支持：
  - 多选题（最多 4 个选项 + "其他"）
  - 开放问答
"""

from __future__ import annotations

import json
import logging
from typing import Callable

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

MAX_CHOICES = 4

_clarify_callback: Callable | None = None

CLARIFY_RESPONSES: dict[str, dict] = {}


def set_clarify_callback(callback: Callable | None) -> None:
    global _clarify_callback
    _clarify_callback = callback


@tool
def clarify_tool(question: str, choices: list[str] | None = None) -> str:
    """向用户提问以获取澄清信息。

    当 LLM 需要从用户那里获取更多信息时使用此工具。
    如果提供了 choices，用户可以从选项中选择，最多 4 个选项。

    Args:
        question: 要问用户的问题
        choices: 可选的选项列表，最多 4 个

    Returns:
        JSON 字符串，包含用户响应
    """
    if not question or not question.strip():
        return json.dumps({"error": "Question text is required."}, ensure_ascii=False)

    question = question.strip()

    if choices is not None:
        if not isinstance(choices, list):
            return json.dumps({"error": "choices must be a list of strings."}, ensure_ascii=False)
        choices = [str(c) for c in choices if c]
        if len(choices) > MAX_CHOICES:
            choices = choices[:MAX_CHOICES]
        if not choices:
            choices = None

    if _clarify_callback is None:
        return json.dumps(
            {"error": "Clarify tool is not available in this execution context."},
            ensure_ascii=False,
        )

    try:
        user_response = _clarify_callback(question, choices)
    except Exception as exc:
        return json.dumps({"error": f"Failed to get user input: {exc}"}, ensure_ascii=False)

    return json.dumps({
        "question": question,
        "choices_offered": choices,
        "user_response": str(user_response).strip(),
    }, ensure_ascii=False)


def clarify(**kwargs) -> str:
    return clarify_tool(
        question=kwargs.get("question", ""),
        choices=kwargs.get("choices"),
    )