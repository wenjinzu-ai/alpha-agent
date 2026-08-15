"""可插拔上下文引擎 - ContextEngine ABC。

上下文引擎控制对话上下文的管理方式。内置 ContextCompressor 是默认实现，
第三方引擎可通过插件系统替换。

PG 优势:
  - JSONB 存储结构化摘要(Resolved/Pending 问题追踪)
  - pg_trgm 搜索历史摘要，跨会话复用
  - 物化视图加速摘要聚合查询
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ContextEngine(ABC):
    """上下文引擎基类，所有引擎必须实现此接口。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """引擎标识符 (e.g. 'compressor', 'noop')."""

    last_prompt_tokens: int = 0
    last_completion_tokens: int = 0
    last_total_tokens: int = 0
    context_length: int = 0
    compression_count: int = 0

    threshold_percent: float = 0.75
    protect_first_n: int = 3
    protect_last_n: int = 6

    @abstractmethod
    def update_from_response(self, usage: Dict[str, Any]) -> None:
        """从 API 响应更新 token 使用统计。"""

    @abstractmethod
    def should_compress(self, prompt_tokens: Optional[int] = None) -> bool:
        """判断此轮是否需要压缩。"""

    @abstractmethod
    def compress(
        self,
        messages: List[Dict[str, Any]],
        current_tokens: Optional[int] = None,
        focus_topic: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """压缩消息列表并返回新的消息列表。"""

    def should_compress_preflight(self, messages: List[Dict[str, Any]]) -> bool:
        return False

    def on_session_start(self, session_id: str) -> None:
        pass

    def on_session_end(self, session_id: str) -> None:
        pass


class NoopContextEngine(ContextEngine):
    """不做任何压缩的上下文引擎。"""

    @property
    def name(self) -> str:
        return "noop"

    def update_from_response(self, usage: Dict[str, Any]) -> None:
        self.last_prompt_tokens = usage.get("prompt_tokens", 0)
        self.last_completion_tokens = usage.get("completion_tokens", 0)
        self.last_total_tokens = usage.get("total_tokens", 0)

    def should_compress(self, prompt_tokens: Optional[int] = None) -> bool:
        return False

    def compress(
        self,
        messages: List[Dict[str, Any]],
        current_tokens: Optional[int] = None,
        focus_topic: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return messages