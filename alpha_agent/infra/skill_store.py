"""Skill Store —— PG 驱动的 Skill 持久化与检索。

借鉴 Hermes 的 skill_manage 设计（create/patch/edit/delete），
但用 PostgreSQL 替代 Markdown 文件，支持 JSONB 查询和全文搜索。

Hermes 参考：
  - tools/skill_manager_tool.py: skill_manage(action=create/patch/edit/delete)
  - tools/skills_tool.py: 技能扫描、加载、平台匹配
  - agent/skill_utils.py: 技能目录管理
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, or_, func, text, cast, String

from alpha_agent.infra.db.database import SessionLocal, init_db
from alpha_agent.infra.db.models import AgentSkill
from alpha_agent.utils.logger import logger


class SkillStore:
    """PG 驱动的技能仓库，提供技能全生命周期管理。"""

    def __init__(self):
        init_db()

    def create_skill(
        self,
        name: str,
        content: str,
        category: str = "general",
        description: str = "",
        trigger_keywords: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        display_name: str = "",
        source: str = "user_created",
        parent_name: Optional[str] = None,
        created_by: str = "user",
    ) -> AgentSkill:
        with SessionLocal() as db:
            existing = db.query(AgentSkill).filter_by(name=name).first()
            if existing:
                raise ValueError(f"Skill '{name}' already exists. Use patch/edit to update.")

            skill = AgentSkill(
                name=name,
                display_name=display_name or name,
                category=category,
                description=description,
                trigger_keywords=trigger_keywords or [],
                content=content,
                metadata_=metadata or {},
                status="active",
                source=source,
                parent_name=parent_name,
                created_by=created_by,
                version=1,
            )
            db.add(skill)
            db.commit()
            db.refresh(skill)
            logger.info(f"Skill created: {name} (category={category})")
            return skill

    def patch_skill(
        self,
        name: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> AgentSkill:
        with SessionLocal() as db:
            skill = db.query(AgentSkill).filter_by(name=name).first()
            if not skill:
                raise ValueError(f"Skill '{name}' not found")

            if replace_all:
                skill.content = skill.content.replace(old_string, new_string)
            else:
                if old_string not in skill.content:
                    raise ValueError(f"old_string not found in skill '{name}'. Use replace_all=True to replace all occurrences.")
                skill.content = skill.content.replace(old_string, new_string, 1)

            skill.version = (skill.version or 0) + 1
            skill.last_patched_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(skill)
            logger.info(f"Skill patched: {name} (version={skill.version})")
            return skill

    def edit_skill(
        self,
        name: str,
        content: Optional[str] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        display_name: Optional[str] = None,
        trigger_keywords: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentSkill:
        with SessionLocal() as db:
            skill = db.query(AgentSkill).filter_by(name=name).first()
            if not skill:
                raise ValueError(f"Skill '{name}' not found")

            if content is not None:
                skill.content = content
            if description is not None:
                skill.description = description
            if category is not None:
                skill.category = category
            if display_name is not None:
                skill.display_name = display_name
            if trigger_keywords is not None:
                skill.trigger_keywords = trigger_keywords
            if metadata is not None:
                skill.metadata_ = metadata

            skill.version = (skill.version or 0) + 1
            skill.last_patched_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(skill)
            logger.info(f"Skill edited: {name} (version={skill.version})")
            return skill

    def delete_skill(self, name: str, force: bool = False) -> bool:
        with SessionLocal() as db:
            skill = db.query(AgentSkill).filter_by(name=name).first()
            if not skill:
                raise ValueError(f"Skill '{name}' not found")
            if skill.pinned and not force:
                raise ValueError(f"Skill '{name}' is pinned. Use force=True or unpin first.")

            db.delete(skill)
            db.commit()
            logger.info(f"Skill deleted: {name}")
            return True

    def fork_skill(
        self,
        name: str,
        new_name: str,
        created_by: str = "user",
    ) -> AgentSkill:
        with SessionLocal() as db:
            original = db.query(AgentSkill).filter_by(name=name).first()
            if not original:
                raise ValueError(f"Skill '{name}' not found")
            if db.query(AgentSkill).filter_by(name=new_name).first():
                raise ValueError(f"Skill '{new_name}' already exists")

            new_skill = AgentSkill(
                name=new_name,
                display_name=new_name,
                category=original.category,
                description=original.description,
                trigger_keywords=original.trigger_keywords,
                content=original.content,
                metadata_=dict(original.metadata_ or {}),
                source="user_created",
                parent_name=name,
                created_by=created_by,
                version=1,
            )
            db.add(new_skill)
            db.commit()
            db.refresh(new_skill)
            logger.info(f"Skill forked: {name} -> {new_name}")
            return new_skill

    def retire_skill(self, name: str) -> AgentSkill:
        with SessionLocal() as db:
            skill = db.query(AgentSkill).filter_by(name=name).first()
            if not skill:
                raise ValueError(f"Skill '{name}' not found")
            skill.status = "retired"
            db.commit()
            db.refresh(skill)
            logger.info(f"Skill retired: {name}")
            return skill

    def get_skill(self, name: str) -> Optional[AgentSkill]:
        with SessionLocal() as db:
            return db.query(AgentSkill).filter_by(name=name).first()

    def list_skills(
        self,
        category: Optional[str] = None,
        status: str = "active",
        source: Optional[str] = None,
        sort_by: str = "name",
        limit: int = 100,
        offset: int = 0,
    ) -> List[AgentSkill]:
        with SessionLocal() as db:
            query = db.query(AgentSkill).filter_by(status=status)
            if category:
                query = query.filter_by(category=category)
            if source:
                query = query.filter_by(source=source)

            if sort_by == "use_count":
                query = query.order_by(AgentSkill.use_count.desc())
            elif sort_by == "created":
                query = query.order_by(AgentSkill.created_at.desc())
            elif sort_by == "updated":
                query = query.order_by(AgentSkill.updated_at.desc())
            else:
                query = query.order_by(AgentSkill.name.asc())

            return query.offset(offset).limit(limit).all()

    def search_skills(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> List[AgentSkill]:
        with SessionLocal() as db:
            search_pattern = f"%{query}%"
            q = db.query(AgentSkill).filter(
                and_(
                    AgentSkill.status == "active",
                    or_(
                        AgentSkill.name.ilike(search_pattern),
                        AgentSkill.description.ilike(search_pattern),
                        AgentSkill.display_name.ilike(search_pattern),
                        cast(AgentSkill.trigger_keywords, String).ilike(search_pattern),
                    ),
                )
            )
            if category:
                q = q.filter_by(category=category)
            return q.order_by(AgentSkill.use_count.desc()).limit(limit).all()

    def record_usage(self, name: str, success: bool = True) -> None:
        with SessionLocal() as db:
            skill = db.query(AgentSkill).filter_by(name=name).first()
            if skill:
                skill.use_count = (skill.use_count or 0) + 1
                if success:
                    skill.success_count = (skill.success_count or 0) + 1
                else:
                    skill.fail_count = (skill.fail_count or 0) + 1
                skill.last_used_at = datetime.now(timezone.utc)
                db.commit()

    def get_categories(self) -> List[str]:
        with SessionLocal() as db:
            rows = db.query(AgentSkill.category).filter_by(status="active").distinct().all()
            return sorted(r[0] for r in rows if r[0])

    def get_stats(self) -> Dict[str, Any]:
        with SessionLocal() as db:
            total = db.query(AgentSkill).filter_by(status="active").count()
            agent_created = db.query(AgentSkill).filter_by(status="active", source="agent_created").count()
            categories = self.get_categories()
            return {
                "total_skills": total,
                "agent_created": agent_created,
                "categories": categories,
                "category_count": len(categories),
            }


skill_store = SkillStore()