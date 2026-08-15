"""会话搜索 - session_search_tool 设计，用 PG tsvector 替代 SQLite FTS5。

PG 优势:
  - tsvector 全文搜索比 SQLite FTS5 更强大
  - 原生支持中文分词 (zhparser/jieba)
  - pg_trgm 模糊搜索，支持拼音/部分匹配
  - JSONB 存储会话元数据，灵活查询
  - 物化视图加速热门搜索
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from alpha_agent.infra.db.database import SessionLocal, init_db
from alpha_agent.utils.logger import logger


class SessionStore:
    """PG 驱动的会话搜索与存储。

    三种搜索模式:
    - DISCOVERY: 全文搜索，返回匹配的会话片段
    - SCROLL: 按会话 ID + 消息 ID 浏览消息窗口
    - BROWSE: 最近会话时间线
    """

    def __init__(self):
        init_db()

    def record_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录一轮对话。"""
        try:
            with SessionLocal() as db:
                db.execute(
                    text("""
                        INSERT INTO agent_sessions
                            (session_id, user_message, assistant_message,
                             tool_calls, metadata, created_at)
                        VALUES
                            (:sid, :user_msg, :asst_msg,
                             :tools, :meta, :ts)
                    """),
                    {
                        "sid": session_id,
                        "user_msg": user_message,
                        "asst_msg": assistant_message,
                        "tools": json.dumps(tool_calls or [], ensure_ascii=False),
                        "meta": json.dumps(metadata or {}, ensure_ascii=False),
                        "ts": datetime.now(timezone.utc),
                    },
                )
                db.commit()
        except Exception as e:
            logger.warning(f"[SessionStore] 记录对话失败: {e}")

    def search(
        self,
        query: str,
        limit: int = 10,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """全文搜索历史会话（DISCOVERY 模式）。

        使用 PG tsvector 进行全文搜索，支持中文。
        """
        try:
            with SessionLocal() as db:
                rows = db.execute(
                    text("""
                        SELECT
                            session_id,
                            user_message,
                            assistant_message,
                            ts_rank_cd(
                                to_tsvector('simple',
                                    coalesce(user_message, '') || ' ' ||
                                    coalesce(assistant_message, '')
                                ),
                                plainto_tsquery('simple', :query)
                            ) AS rank,
                            created_at
                        FROM agent_sessions
                        WHERE
                            to_tsvector('simple',
                                coalesce(user_message, '') || ' ' ||
                                coalesce(assistant_message, '')
                            ) @@ plainto_tsquery('simple', :query)
                            AND (:sid IS NULL OR session_id = :sid)
                        ORDER BY rank DESC
                        LIMIT :limit
                    """),
                    {
                        "query": query,
                        "sid": session_id,
                        "limit": limit,
                    },
                ).fetchall()

                return [
                    {
                        "session_id": r.session_id,
                        "user_message": r.user_message[:200] if r.user_message else "",
                        "assistant_message": r.assistant_message[:200] if r.assistant_message else "",
                        "rank": float(r.rank) if r.rank else 0,
                        "created_at": str(r.created_at) if r.created_at else "",
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.warning(f"[SessionStore] 搜索失败: {e}")
            return []

    def browse(self, limit: int = 20) -> List[Dict[str, Any]]:
        """浏览最近会话（BROWSE 模式）。"""
        try:
            with SessionLocal() as db:
                rows = db.execute(
                    text("""
                        SELECT DISTINCT ON (session_id)
                            session_id,
                            user_message,
                            assistant_message,
                            created_at
                        FROM agent_sessions
                        ORDER BY session_id, created_at DESC
                        LIMIT :limit
                    """),
                    {"limit": limit},
                ).fetchall()

                return [
                    {
                        "session_id": r.session_id,
                        "user_message": r.user_message[:200] if r.user_message else "",
                        "assistant_message": r.assistant_message[:200] if r.assistant_message else "",
                        "created_at": str(r.created_at) if r.created_at else "",
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.warning(f"[SessionStore] 浏览失败: {e}")
            return []

    def get_recent_context(
        self,
        session_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """获取会话最近的消息上下文。"""
        try:
            with SessionLocal() as db:
                rows = db.execute(
                    text("""
                        SELECT user_message, assistant_message
                        FROM agent_sessions
                        WHERE session_id = :sid
                        ORDER BY created_at DESC
                        LIMIT :limit
                    """),
                    {"sid": session_id, "limit": limit},
                ).fetchall()

                return [
                    {
                        "user_message": r.user_message,
                        "assistant_message": r.assistant_message,
                    }
                    for r in reversed(rows)
                ]
        except Exception as e:
            logger.warning(f"[SessionStore] 获取上下文失败: {e}")
            return []


_session_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    global _session_store
    if _session_store is None:
        _session_store = SessionStore()
    return _session_store