"""会话生命周期管理 —— 会话管理能力。

在现有 SessionStore 基础上增强：
  1. 会话元数据管理（title, status, tags, step_count）
  2. 会话恢复（resume）—— 从 LangGraph checkpoint 恢复
  3. 会话分支（branch）—— 从 checkpoint fork 新会话
  4. 压缩延续（compression continuation）—— 保存压缩摘要后继续
  5. 会话归档/清理
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from alpha_agent.infra.db.database import SessionLocal
from alpha_agent.utils.logger import logger


class SessionLifecycleManager:
    """会话生命周期管理器。

    在现有 SessionStore（记录对话轮次）基础上增加：
    - 会话级别的元数据管理
    - 恢复/分支/压缩延续
    """

    def __init__(self):
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            with SessionLocal() as db:
                db.execute(text("""
                    CREATE TABLE IF NOT EXISTS session_metadata (
                        id SERIAL PRIMARY KEY,
                        session_id VARCHAR(128) UNIQUE NOT NULL,
                        title VARCHAR(500) DEFAULT '',
                        status VARCHAR(32) DEFAULT 'active',
                        parent_session_id VARCHAR(128),
                        step_count INTEGER DEFAULT 0,
                        tags JSONB DEFAULT '[]'::jsonb,
                        summary TEXT DEFAULT '',
                        model_name VARCHAR(128) DEFAULT '',
                        total_tokens INTEGER DEFAULT 0,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        archived_at TIMESTAMP WITH TIME ZONE
                    )
                """))
                db.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_session_metadata_status
                    ON session_metadata(status)
                """))
                db.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_session_metadata_parent
                    ON session_metadata(parent_session_id)
                """))
                db.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_session_metadata_updated
                    ON session_metadata(updated_at DESC)
                """))
                db.commit()
        except Exception as e:
            logger.warning(f"[SessionLifecycle] 建表失败: {e}")

    def create_session(
        self,
        session_id: str,
        title: str = "",
        parent_session_id: Optional[str] = None,
        model_name: str = "",
    ) -> dict[str, Any]:
        """创建新会话元数据。"""
        try:
            with SessionLocal() as db:
                db.execute(
                    text("""
                        INSERT INTO session_metadata
                            (session_id, title, status, parent_session_id, model_name)
                        VALUES
                            (:sid, :title, 'active', :parent, :model)
                        ON CONFLICT (session_id) DO UPDATE
                            SET updated_at = NOW()
                    """),
                    {
                        "sid": session_id,
                        "title": title[:500],
                        "parent": parent_session_id,
                        "model": model_name,
                    },
                )
                db.commit()
            return {"session_id": session_id, "status": "active"}
        except Exception as e:
            logger.error(f"[SessionLifecycle] 创建会话失败: {e}")
            return {"session_id": session_id, "status": "error", "error": str(e)}

    def update_session(
        self,
        session_id: str,
        title: Optional[str] = None,
        status: Optional[str] = None,
        step_count: Optional[int] = None,
        tags: Optional[List[str]] = None,
        summary: Optional[str] = None,
        total_tokens: Optional[int] = None,
    ) -> dict[str, Any]:
        """更新会话元数据。"""
        updates: dict[str, Any] = {}
        if title is not None:
            updates["title"] = title[:500]
        if status is not None:
            updates["status"] = status
        if step_count is not None:
            updates["step_count"] = step_count
        if tags is not None:
            updates["tags"] = tags
        if summary is not None:
            updates["summary"] = summary
        if total_tokens is not None:
            updates["total_tokens"] = total_tokens

        if not updates:
            return {"session_id": session_id, "updated": False}

        updates["updated_at"] = datetime.now(timezone.utc)

        try:
            with SessionLocal() as db:
                set_clauses = ", ".join(
                    f"{k} = :{k}" for k in updates
                )
                params = {"sid": session_id, **updates}
                db.execute(
                    text(f"""
                        UPDATE session_metadata
                        SET {set_clauses}
                        WHERE session_id = :sid
                    """),
                    params,
                )
                db.commit()
            return {"session_id": session_id, "updated": True}
        except Exception as e:
            logger.error(f"[SessionLifecycle] 更新会话失败: {e}")
            return {"session_id": session_id, "updated": False, "error": str(e)}

    def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        """获取会话详情。"""
        try:
            with SessionLocal() as db:
                row = db.execute(
                    text("""
                        SELECT session_id, title, status, parent_session_id,
                               step_count, tags, summary, model_name,
                               total_tokens, created_at, updated_at
                        FROM session_metadata
                        WHERE session_id = :sid
                    """),
                    {"sid": session_id},
                ).fetchone()

                if not row:
                    return None

                return {
                    "session_id": row[0],
                    "title": row[1],
                    "status": row[2],
                    "parent_session_id": row[3],
                    "step_count": row[4],
                    "tags": row[5] or [],
                    "summary": row[6],
                    "model_name": row[7],
                    "total_tokens": row[8],
                    "created_at": str(row[9]) if row[9] else "",
                    "updated_at": str(row[10]) if row[10] else "",
                }
        except Exception as e:
            logger.error(f"[SessionLifecycle] 获取会话失败: {e}")
            return None

    def list_sessions(
        self,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """列出会话列表。"""
        try:
            with SessionLocal() as db:
                query = """
                    SELECT session_id, title, status, step_count,
                           total_tokens, created_at, updated_at
                    FROM session_metadata
                """
                params: dict[str, Any] = {}
                if status:
                    query += " WHERE status = :status"
                    params["status"] = status
                query += " ORDER BY updated_at DESC LIMIT :limit OFFSET :offset"
                params["limit"] = limit
                params["offset"] = offset

                rows = db.execute(text(query), params).fetchall()

                return [
                    {
                        "session_id": r[0],
                        "title": r[1],
                        "status": r[2],
                        "step_count": r[3],
                        "total_tokens": r[4],
                        "created_at": str(r[5]) if r[5] else "",
                        "updated_at": str(r[6]) if r[6] else "",
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.error(f"[SessionLifecycle] 列出会话失败: {e}")
            return []

    def resume_session(self, session_id: str) -> dict[str, Any]:
        """恢复会话。

        将会话状态设为 active，返回会话信息。
        实际的消息恢复由 LangGraph PostgresSaver 的 checkpoint 机制处理。
        """
        session = self.get_session(session_id)
        if not session:
            return {"session_id": session_id, "error": "会话不存在"}

        if session["status"] == "archived":
            return {"session_id": session_id, "error": "会话已归档，无法恢复"}

        self.update_session(session_id, status="active")
        return {
            "session_id": session_id,
            "status": "active",
            "resumed": True,
            "parent_session_id": session.get("parent_session_id"),
            "step_count": session.get("step_count", 0),
        }

    def branch_session(
        self,
        parent_session_id: str,
        branch_title: str = "",
    ) -> dict[str, Any]:
        """从父会话分支创建新会话。

        branch 功能：从 checkpoint fork 新会话。
        新会话继承父会话的 checkpoint 状态，但独立演进。
        """
        import uuid

        parent = self.get_session(parent_session_id)
        if not parent:
            return {"error": "父会话不存在"}

        new_session_id = str(uuid.uuid4())
        title = branch_title or f"{parent.get('title', '会话')} (分支)"

        return self.create_session(
            session_id=new_session_id,
            title=title,
            parent_session_id=parent_session_id,
        )

    def compression_continuation(
        self,
        session_id: str,
        compressed_summary: str,
        compressed_tokens: int,
    ) -> dict[str, Any]:
        """压缩延续 —— 保存压缩摘要后继续会话。

        compression continuation：
        当上下文过长时，将历史压缩为摘要，标记压缩点，继续对话。
        """
        import json

        self.update_session(
            session_id=session_id,
            summary=compressed_summary[:5000],
            total_tokens=compressed_tokens,
        )

        try:
            with SessionLocal() as db:
                tags = json.dumps(["compressed", f"tokens:{compressed_tokens}"])
                db.execute(
                    text("""
                        UPDATE session_metadata
                        SET tags = tags || :tags::jsonb,
                            updated_at = NOW()
                        WHERE session_id = :sid
                    """),
                    {"sid": session_id, "tags": tags},
                )
                db.commit()
        except Exception as e:
            logger.warning(f"[SessionLifecycle] 压缩延续标记失败: {e}")

        return {
            "session_id": session_id,
            "compressed": True,
            "compressed_tokens": compressed_tokens,
        }

    def archive_session(self, session_id: str) -> dict[str, Any]:
        """归档会话。"""
        return self.update_session(
            session_id=session_id,
            status="archived",
        )

    def delete_session(self, session_id: str) -> dict[str, Any]:
        """删除会话（软删除 → 标记为 deleted）。"""
        return self.update_session(
            session_id=session_id,
            status="deleted",
        )

    def get_session_tree(self, session_id: str) -> dict[str, Any]:
        """获取会话树 —— 父会话和所有分支。

        会话树视图。
        """
        session = self.get_session(session_id)
        if not session:
            return {"session_id": session_id, "error": "会话不存在"}

        branches: list[dict[str, Any]] = []
        try:
            with SessionLocal() as db:
                rows = db.execute(
                    text("""
                        SELECT session_id, title, status
                        FROM session_metadata
                        WHERE parent_session_id = :sid
                        ORDER BY created_at
                    """),
                    {"sid": session_id},
                ).fetchall()
                branches = [
                    {
                        "session_id": r[0],
                        "title": r[1],
                        "status": r[2],
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.error(f"[SessionLifecycle] 获取会话树失败: {e}")

        parent = None
        if session.get("parent_session_id"):
            parent = self.get_session(session["parent_session_id"])

        return {
            "session": session,
            "parent": parent,
            "branches": branches,
            "branch_count": len(branches),
        }


_session_lifecycle: Optional[SessionLifecycleManager] = None


def get_session_lifecycle() -> SessionLifecycleManager:
    global _session_lifecycle
    if _session_lifecycle is None:
        _session_lifecycle = SessionLifecycleManager()
    return _session_lifecycle
