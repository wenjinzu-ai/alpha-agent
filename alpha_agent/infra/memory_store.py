"""Memory Store —— PG 驱动的三层记忆读写。

借鉴 Hermes 的 memory_tool.py 和 memory_provider.py 设计，
但用 PostgreSQL 替代 Markdown 文件，支持结构化查询和标签检索。

三层记忆模型：
  1. Frozen Memory  - 持久的用户画像、偏好、知识
  2. Episodic Memory - 会话级经验片段（自动过期/归档）
  3. SkillRef Memory  - 成功使用的 Skill 引用

Hermes 参考：
  - tools/memory_tool.py: memory(action=add/delete/replace/consolidate/view)
  - agent/memory_provider.py: MemoryProvider 抽象接口
  - agent/memory_manager.py: 记忆管理逻辑
"""
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, or_

from alpha_agent.infra.db.database import SessionLocal, init_db
from alpha_agent.infra.db.models import AgentMemory
from alpha_agent.utils.logger import logger


class MemoryStore:
    """PG 驱动的三层记忆仓库。"""

    # Episodic 记忆默认 TTL（30 天）
    DEFAULT_EPISODIC_TTL_DAYS = 30

    # Frozen 记忆每层最大条数
    MAX_FROZEN_ENTRIES = 50

    def __init__(self, user_id: str = "default"):
        init_db()
        self.user_id = user_id

    def add(
        self,
        content: str,
        layer: str = "episodic",
        session_id: str = "",
        tags: Optional[List[str]] = None,
        importance: float = 0.5,
        summary: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        skill_name: Optional[str] = None,
        source: str = "conversation",
        ttl_days: Optional[int] = None,
    ) -> AgentMemory:
        with SessionLocal() as db:
            now = datetime.now(timezone.utc)
            expires_at = None
            if layer == "episodic" and ttl_days is not None:
                expires_at = now + timedelta(days=ttl_days)
            elif layer == "episodic":
                expires_at = now + timedelta(days=self.DEFAULT_EPISODIC_TTL_DAYS)

            memory = AgentMemory(
                session_id=session_id,
                user_id=self.user_id,
                layer=layer,
                content=content,
                summary=summary or content[:200],
                tags=tags or [],
                metadata_=metadata or {},
                skill_name=skill_name,
                importance=min(max(importance, 0.0), 1.0),
                access_count=0,
                last_accessed_at=now,
                source=source,
                status="active",
                expires_at=expires_at,
            )
            db.add(memory)
            db.commit()
            db.refresh(memory)

            self._enforce_frozen_limit(db)
            return memory

    def add_many(
        self,
        entries: List[Dict[str, Any]],
        layer: str = "episodic",
        session_id: str = "",
    ) -> List[AgentMemory]:
        results = []
        for entry in entries:
            result = self.add(
                content=entry.get("content", ""),
                layer=entry.get("layer", layer),
                session_id=entry.get("session_id", session_id),
                tags=entry.get("tags"),
                importance=entry.get("importance", 0.5),
                summary=entry.get("summary", ""),
                metadata=entry.get("metadata"),
                skill_name=entry.get("skill_name"),
                source=entry.get("source", "conversation"),
            )
            results.append(result)
        return results

    def replace(
        self,
        old_string: str,
        new_string: str,
        layer: Optional[str] = None,
        replace_all: bool = False,
    ) -> List[AgentMemory]:
        with SessionLocal() as db:
            query = db.query(AgentMemory).filter(
                and_(
                    AgentMemory.user_id == self.user_id,
                    AgentMemory.status == "active",
                )
            )
            if layer:
                query = query.filter_by(layer=layer)

            memories = query.all()
            updated = []
            for mem in memories:
                if old_string in mem.content:
                    if replace_all:
                        mem.content = mem.content.replace(old_string, new_string)
                    else:
                        mem.content = mem.content.replace(old_string, new_string, 1)
                    updated.append(mem)

            if updated:
                db.commit()
                for mem in updated:
                    db.refresh(mem)
            return updated

    def delete(self, memory_id: int) -> bool:
        with SessionLocal() as db:
            mem = db.query(AgentMemory).filter_by(id=memory_id, user_id=self.user_id).first()
            if not mem:
                raise ValueError(f"Memory #{memory_id} not found")
            db.delete(mem)
            db.commit()
            return True

    def consolidate(
        self,
        memory_ids: List[int],
        new_content: str,
        new_summary: str = "",
        new_tags: Optional[List[str]] = None,
    ) -> AgentMemory:
        with SessionLocal() as db:
            if len(memory_ids) < 2:
                raise ValueError("Consolidation requires at least 2 source memories")

            sources = db.query(AgentMemory).filter(
                AgentMemory.id.in_(memory_ids),
                AgentMemory.user_id == self.user_id,
            ).all()
            if len(sources) < 2:
                raise ValueError("Not enough valid source memories found")

            merged = AgentMemory(
                session_id="",
                user_id=self.user_id,
                layer="frozen",
                content=new_content,
                summary=new_summary or new_content[:200],
                tags=new_tags or [],
                importance=0.8,
                source="consolidated",
                status="active",
            )
            db.add(merged)
            db.flush()

            for src in sources:
                src.status = "consolidated"

            db.commit()
            db.refresh(merged)
            self._enforce_frozen_limit(db)
            return merged

    def view(
        self,
        layer: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[AgentMemory]:
        with SessionLocal() as db:
            query = db.query(AgentMemory).filter(
                and_(
                    AgentMemory.user_id == self.user_id,
                    AgentMemory.status == "active",
                )
            )
            if layer:
                query = query.filter_by(layer=layer)
            if tags:
                for tag in tags:
                    query = query.filter(AgentMemory.tags.contains([tag]))

            query = query.order_by(AgentMemory.importance.desc(), AgentMemory.created_at.desc())
            return query.offset(offset).limit(limit).all()

    def search(
        self,
        query: str,
        layer: Optional[str] = None,
        limit: int = 20,
    ) -> List[AgentMemory]:
        with SessionLocal() as db:
            search_pattern = f"%{query}%"
            q = db.query(AgentMemory).filter(
                and_(
                    AgentMemory.user_id == self.user_id,
                    AgentMemory.status == "active",
                    or_(
                        AgentMemory.content.ilike(search_pattern),
                        AgentMemory.summary.ilike(search_pattern),
                    ),
                )
            )
            if layer:
                q = q.filter_by(layer=layer)
            return q.order_by(AgentMemory.importance.desc()).limit(limit).all()

    def get_for_system_prompt(self, limit: int = 10) -> str:
        with SessionLocal() as db:
            frozen = db.query(AgentMemory).filter(
                and_(
                    AgentMemory.user_id == self.user_id,
                    AgentMemory.layer == "frozen",
                    AgentMemory.status == "active",
                )
            ).order_by(AgentMemory.importance.desc()).limit(limit).all()

            if not frozen:
                return ""

            lines = ["## 用户画像与偏好 (Frozen Memory)"]
            for mem in frozen:
                if mem.summary:
                    lines.append(f"- {mem.summary}")
            return "\n".join(lines)

    def get_recent_episodic(self, session_id: str = "", limit: int = 5) -> str:
        with SessionLocal() as db:
            query = db.query(AgentMemory).filter(
                and_(
                    AgentMemory.user_id == self.user_id,
                    AgentMemory.layer == "episodic",
                    AgentMemory.status == "active",
                )
            )
            if session_id:
                query = query.filter_by(session_id=session_id)
            episodes = query.order_by(AgentMemory.created_at.desc()).limit(limit).all()

            if not episodes:
                return ""

            lines = ["## 最近经验 (Episodic Memory)"]
            for mem in episodes:
                if mem.summary:
                    lines.append(f"- {mem.summary}")
            return "\n".join(lines)

    def get_skill_refs(self, skill_name: str, limit: int = 5) -> List[AgentMemory]:
        with SessionLocal() as db:
            return db.query(AgentMemory).filter(
                and_(
                    AgentMemory.user_id == self.user_id,
                    AgentMemory.layer == "skill_ref",
                    AgentMemory.skill_name == skill_name,
                    AgentMemory.status == "active",
                )
            ).order_by(AgentMemory.created_at.desc()).limit(limit).all()

    def record_access(self, memory_id: int) -> None:
        with SessionLocal() as db:
            mem = db.query(AgentMemory).filter_by(id=memory_id).first()
            if mem:
                mem.access_count = (mem.access_count or 0) + 1
                mem.last_accessed_at = datetime.now(timezone.utc)
                db.commit()

    def cleanup_expired(self) -> int:
        with SessionLocal() as db:
            now = datetime.now(timezone.utc)
            expired = db.query(AgentMemory).filter(
                and_(
                    AgentMemory.status == "active",
                    AgentMemory.expires_at.isnot(None),
                    AgentMemory.expires_at < now,
                )
            ).all()
            count = len(expired)
            for mem in expired:
                mem.status = "archived"
                mem.archived_at = now
            db.commit()
            if count:
                logger.info(f"Archived {count} expired memories")
            return count

    def _enforce_frozen_limit(self, db) -> None:
        frozen_count = db.query(AgentMemory).filter(
            and_(
                AgentMemory.user_id == self.user_id,
                AgentMemory.layer == "frozen",
                AgentMemory.status == "active",
            )
        ).count()
        if frozen_count > self.MAX_FROZEN_ENTRIES:
            excess = frozen_count - self.MAX_FROZEN_ENTRIES
            oldest = db.query(AgentMemory).filter(
                and_(
                    AgentMemory.user_id == self.user_id,
                    AgentMemory.layer == "frozen",
                    AgentMemory.status == "active",
                )
            ).order_by(AgentMemory.importance.asc(), AgentMemory.created_at.asc()).limit(excess).all()
            for mem in oldest:
                mem.status = "archived"
            db.commit()
            if oldest:
                logger.info(f"Archived {len(oldest)} low-importance frozen memories (limit exceeded)")

    def get_stats(self) -> Dict[str, Any]:
        with SessionLocal() as db:
            frozen = db.query(AgentMemory).filter_by(user_id=self.user_id, layer="frozen", status="active").count()
            episodic = db.query(AgentMemory).filter_by(user_id=self.user_id, layer="episodic", status="active").count()
            skill_ref = db.query(AgentMemory).filter_by(user_id=self.user_id, layer="skill_ref", status="active").count()
            return {
                "frozen": frozen,
                "episodic": episodic,
                "skill_ref": skill_ref,
                "total": frozen + episodic + skill_ref,
            }


memory_store = MemoryStore()