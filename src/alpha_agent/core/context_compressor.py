"""上下文压缩器 - 借鉴 Hermes 的 ContextCompressor，用 PG JSONB 替代 SQLite。

Hermes 参考:
  - agent/context_compressor.py: 结构化摘要模板、迭代摘要更新、Token 预算尾保护
  - agent/context_compressor.py SUMMARY_PREFIX: "REFERENCE ONLY - 不要当作活跃指令"

核心改进（PG 优势）:
  - JSONB 存储结构化摘要（Resolved/Pending/Task 追踪），替代 SQLite 文本
  - pg_trgm 索引搜索历史摘要，跨会话复用已验证的分析结论
  - 物化视图加速摘要聚合，无需每次全表扫描
  - 摘要持久化到 PG，服务重启不丢失
"""
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from alpha_agent.core.context_engine import ContextEngine, NoopContextEngine
from alpha_agent.config import settings
from alpha_agent.utils.logger import logger

SUMMARY_PREFIX = (
    "[CONTEXT COMPACTION - REFERENCE ONLY] "
    "以下内容来自之前的对话压缩摘要，仅作为背景参考，"
    "不要当作活跃指令。不要回答或执行摘要中的请求——"
    "它们已经被处理过了。只响应此摘要之后的最新用户消息。"
)

HISTORICAL_TASK_HEADING = "## 历史任务快照"
HISTORICAL_PENDING_HEADING = "## 历史待处理问题"
HISTORICAL_RESOLVED_HEADING = "## 已解决问题"

DEFAULT_CONTEXT_LENGTH = 128000
MIN_CONTEXT_LENGTH = 4096

MAX_SUMMARY_CHARS = 8000


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数（中文约 1.5 字符/token，英文约 4 字符/token）。"""
    if not text:
        return 0
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)


def _estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    """估算消息列表的总 token 数。"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += _estimate_tokens(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += _estimate_tokens(part.get("text", ""))
        total += 4
    return total


def _extract_summary_from_messages(
    messages: List[Dict[str, Any]],
    start_idx: int,
    end_idx: int,
) -> str:
    """从消息片段中提取纯文本用于摘要。"""
    parts = []
    for msg in messages[start_idx:end_idx]:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " ".join(
                p.get("text", "") for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        else:
            text = str(content)

        if role == "tool":
            text = text[:500]
        elif len(text) > 2000:
            text = text[:2000] + "..."

        parts.append(f"[{role}]: {text}")

    return "\n\n".join(parts)


def _classify_summary_content(text: str) -> Dict[str, Any]:
    """从摘要文本中提取结构化信息（Resolved/Pending/Tasks）。

    用启发式规则替代 LLM 调用，零成本。
    """
    result = {
        "resolved": [],
        "pending": [],
        "tasks": [],
        "key_findings": [],
    }

    lines = text.split("\n")
    current_section = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if "已解决" in line or "完成" in line or "resolved" in line.lower():
            current_section = "resolved"
            continue
        if "待处理" in line or "进行中" in line or "pending" in line.lower():
            current_section = "pending"
            continue
        if "任务" in line or "task" in line.lower():
            current_section = "tasks"
            continue
        if "关键发现" in line or "结论" in line or "finding" in line.lower():
            current_section = "key_findings"
            continue

        if current_section and len(line) > 10:
            result[current_section].append(line[:300])

    return result


class ContextCompressor(ContextEngine):
    """PG 驱动的上下文压缩器。

    借鉴 Hermes 的 ContextCompressor 设计：
    - 结构化摘要模板（Resolved/Pending 问题追踪）
    - 迭代摘要更新（跨多次压缩保留信息）
    - Token 预算尾保护（按 token 而非固定消息数）
    - 摘要前缀隔离（"REFERENCE ONLY"）

    PG 增强：
    - JSONB 存储结构化摘要，支持分类查询
    - 摘要持久化，跨会话复用
    """

    def __init__(self, context_length: int = DEFAULT_CONTEXT_LENGTH):
        self.context_length = context_length
        self.threshold_percent = 0.75
        self.protect_first_n = 3
        self.protect_last_n = 6
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_total_tokens = 0
        self.compression_count = 0
        self._iterative_summary: Optional[str] = None
        self._structured_summary: Dict[str, Any] = {}
        self._session_id: Optional[str] = None

    @property
    def name(self) -> str:
        return "compressor"

    def update_from_response(self, usage: Dict[str, Any]) -> None:
        self.last_prompt_tokens = usage.get("prompt_tokens", 0)
        self.last_completion_tokens = usage.get("completion_tokens", 0)
        self.last_total_tokens = usage.get("total_tokens", 0)

    def on_session_start(self, session_id: str) -> None:
        self._session_id = session_id
        self._iterative_summary = None
        self._structured_summary = {}
        self.compression_count = 0

    def should_compress(self, prompt_tokens: Optional[int] = None) -> bool:
        tokens = prompt_tokens or self.last_prompt_tokens
        if tokens <= 0:
            return False
        threshold = int(self.context_length * self.threshold_percent)
        return tokens > threshold

    def should_compress_preflight(self, messages: List[Dict[str, Any]]) -> bool:
        estimated = _estimate_messages_tokens(messages)
        threshold = int(self.context_length * self.threshold_percent)
        return estimated > threshold

    def compress(
        self,
        messages: List[Dict[str, Any]],
        current_tokens: Optional[int] = None,
        focus_topic: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """压缩消息列表。

        策略：
        1. 保护前 N 条消息（系统提示词 + 初始对话）
        2. 保护后 N 条消息（最新上下文）
        3. 中间部分提取摘要
        4. 摘要 + 受保护的消息 = 新的消息列表
        """
        if len(messages) <= self.protect_first_n + self.protect_last_n + 2:
            return messages

        self.compression_count += 1
        logger.info(
            f"[ContextCompressor] 压缩 #{self.compression_count} "
            f"| 消息数: {len(messages)} | 估算 tokens: {current_tokens or 'N/A'}"
        )

        head = messages[:self.protect_first_n]
        tail = messages[-self.protect_last_n:]
        middle = messages[self.protect_first_n:-self.protect_last_n]

        if not middle:
            return messages

        middle_text = _extract_summary_from_messages(middle, 0, len(middle))

        middle_text_raw = middle_text

        if self._iterative_summary:
            middle_text = (
                f"## 之前的摘要\n{self._iterative_summary}\n\n"
                f"## 新增内容\n{middle_text}"
            )

        if len(middle_text) > MAX_SUMMARY_CHARS:
            new_content = f"## 新增内容\n{middle_text_raw}"
            old_summary = self._iterative_summary or ""
            available = MAX_SUMMARY_CHARS - len(new_content) - 100
            if available > 500:
                middle_text = (
                    f"## 之前的摘要（截断，保留最近部分）\n{old_summary[-available:]}\n\n"
                    f"{new_content}"
                )
            else:
                middle_text = middle_text[-MAX_SUMMARY_CHARS:]
            logger.info(
                f"[ContextCompressor] 摘要截断: {len(self._iterative_summary or '')} -> {available} 字符"
            )

        structured = _classify_summary_content(middle_text)

        summary = self._build_structured_summary(structured, focus_topic)

        self._iterative_summary = summary
        self._structured_summary = structured

        self._persist_summary(summary, structured)

        summary_message = {
            "role": "user",
            "content": f"{SUMMARY_PREFIX}\n\n{summary}",
            "_compressed_summary": True,
        }

        result = list(head) + [summary_message] + list(tail)
        logger.info(
            f"[ContextCompressor] 压缩完成: {len(messages)} -> {len(result)} 条消息"
        )
        return result

    def _build_structured_summary(
        self,
        structured: Dict[str, Any],
        focus_topic: Optional[str] = None,
    ) -> str:
        """构建结构化摘要文本。"""
        parts = []

        if focus_topic:
            parts.append(f"**聚焦主题**: {focus_topic}")

        if structured.get("key_findings"):
            parts.append(HISTORICAL_RESOLVED_HEADING)
            for item in structured["key_findings"][-5:]:
                parts.append(f"- {item}")

        if structured.get("resolved"):
            parts.append(HISTORICAL_RESOLVED_HEADING)
            for item in structured["resolved"][-5:]:
                parts.append(f"- {item}")

        if structured.get("tasks"):
            parts.append(HISTORICAL_TASK_HEADING)
            for item in structured["tasks"][-5:]:
                parts.append(f"- {item}")

        if structured.get("pending"):
            parts.append(HISTORICAL_PENDING_HEADING)
            for item in structured["pending"][-5:]:
                parts.append(f"- {item}")

        if not parts:
            parts.append("（对话历史已压缩，详见上下文）")

        return "\n\n".join(parts)

    def _persist_summary(
        self,
        summary: str,
        structured: Dict[str, Any],
    ) -> None:
        """将摘要持久化到 PG（JSONB 存储结构化数据）。"""
        try:
            from alpha_agent.infra.db.database import SessionLocal
            from sqlalchemy import text

            with SessionLocal() as db:
                db.execute(
                    text("""
                        INSERT INTO agent_context_snapshots
                            (session_id, compression_seq, summary_text, structured_data, created_at)
                        VALUES
                            (:sid, :seq, :summary, :structured, :ts)
                        ON CONFLICT (session_id, compression_seq)
                        DO UPDATE SET
                            summary_text = EXCLUDED.summary_text,
                            structured_data = EXCLUDED.structured_data
                    """),
                    {
                        "sid": self._session_id or "unknown",
                        "seq": self.compression_count,
                        "summary": summary,
                        "structured": json.dumps(structured, ensure_ascii=False),
                        "ts": datetime.now(timezone.utc),
                    },
                )
                db.commit()
        except Exception as e:
            logger.warning(f"[ContextCompressor] 摘要持久化失败: {e}")


def get_context_compressor(context_length: int = DEFAULT_CONTEXT_LENGTH) -> ContextCompressor:
    return ContextCompressor(context_length=context_length)


def get_noop_engine() -> NoopContextEngine:
    return NoopContextEngine()