"""学习图谱。

将"学习过程可视化"的图谱数据组装起来，供前端渲染。

聚焦于 profile 学习到的、可操作的内容：
  - 非预设、agent 创建或使用过的技能
  - 记忆块作为一等图谱节点
  - 技能关联（related_skills）+ 记忆-技能关联（词法重叠推导）
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

from alpha_agent.infra.db.database import SessionLocal
from alpha_agent.infra.db.models import AgentSkill, AgentMemory
from alpha_agent.utils.logger import logger


@dataclass
class SkillNode:
    name: str
    category: str
    source: str = "profile"
    timestamp: Optional[int] = None
    use_count: int = 0
    state: str = "active"
    created_by: Optional[str] = None
    pinned: bool = False
    related: list[str] = field(default_factory=list)


def _to_int_ts(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        if isinstance(value, datetime):
            return int(value.timestamp())
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def build_skill_nodes() -> dict[str, SkillNode]:
    """从 PG 的 agent_skills 表构建 SkillNode 列表。

    build_skill_nodes，从 Markdown 文件改为从 PG 读取。
    """
    nodes: dict[str, SkillNode] = {}
    try:
        with SessionLocal() as db:
            skills = db.query(AgentSkill).all()
            for skill in skills:
                ts = _to_int_ts(skill.created_at)
                metadata = skill.metadata_ or {}
                related = metadata.get("related_skills", [])
                if isinstance(related, str):
                    related = [r.strip() for r in related.strip("[]").split(",") if r.strip()]

                nodes[skill.name] = SkillNode(
                    name=skill.name,
                    category=skill.category or "general",
                    source=skill.source or "profile",
                    timestamp=ts,
                    use_count=skill.use_count or 0,
                    state=skill.status or "active",
                    created_by=skill.created_by,
                    pinned=bool(skill.pinned),
                    related=related,
                )
    except Exception as e:
        logger.error(f"[LearningGraph] 构建技能节点失败: {e}")

    return nodes


def build_edges(nodes: dict[str, SkillNode]) -> list[tuple[str, str]]:
    """从 related_skills 声明构建技能之间的边。

    build_edges 逻辑。
    """
    edges: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for name, node in nodes.items():
        for related in node.related:
            if related in nodes:
                key = tuple(sorted([name, related]))
                if key not in seen:
                    seen.add(key)
                    edges.append((name, related))
    return edges


def density_stats(
    nodes: dict[str, SkillNode], edges: list[tuple[str, str]]
) -> dict[str, Any]:
    """计算图谱密度统计。

    density_stats。
    """
    linked: set[str] = set()
    for a, b in edges:
        linked.add(a)
        linked.add(b)
    cats: dict[str, int] = {}
    for n in nodes.values():
        cats[n.category] = cats.get(n.category, 0) + 1
    n = len(nodes) or 1
    return {
        "nodes": len(nodes),
        "related_edges": len(edges),
        "edges_per_node": round(len(edges) / n, 3),
        "linked_nodes": len(linked),
        "isolated_pct": round(100 * (n - len(linked)) / n, 1),
        "categories": len(cats),
        "agent_created": sum(1 for x in nodes.values() if x.created_by == "agent"),
        "used": sum(1 for x in nodes.values() if x.use_count > 0),
        "top_categories": sorted(cats.items(), key=lambda kv: -kv[1])[:8],
    }


def _memory_cards() -> list[dict[str, Any]]:
    """从 PG 的 agent_memory 表读取记忆卡片。

    _memory_cards，从 Markdown 文件改为从 PG 读取。
    """
    cards: list[dict[str, Any]] = []
    try:
        with SessionLocal() as db:
            memories = (
                db.query(AgentMemory)
                .filter(AgentMemory.status == "active")
                .order_by(AgentMemory.importance.desc())
                .limit(50)
                .all()
            )
            for mem in memories:
                content = mem.content or ""
                first_line = content.split("\n")[0].strip().lstrip("# ").strip()
                ts = _to_int_ts(mem.created_at)
                cards.append({
                    "source": mem.layer or "episodic",
                    "timestamp": ts,
                    "title": (first_line[:80] + "…") if len(first_line) > 80 else first_line,
                    "body": content[:1200],
                    "importance": mem.importance or 0.5,
                    "skill_name": mem.skill_name,
                })
    except Exception as e:
        logger.error(f"[LearningGraph] 构建记忆卡片失败: {e}")

    return cards


def _tokenize(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9\u4e00-\u9fff]+", text.lower()) if len(t) >= 2}


def _memory_skill_edges(
    memory_cards: list[dict[str, Any]], skills: list[SkillNode]
) -> list[tuple[str, str]]:
    """推导记忆-技能之间的边。

    基于词法重叠：如果记忆内容包含技能名称或关键词，建立关联。
    _memory_skill_edges。
    """
    edges: list[tuple[str, str]] = []
    skill_meta = [(s, _tokenize(s.name), s.name.lower()) for s in skills]
    for idx, card in enumerate(memory_cards):
        mem_id = f"memory:{card['source']}:{idx}"
        text = f"{card.get('title', '')}\n{card.get('body', '')}".lower()
        text_tokens = _tokenize(text)
        scored: list[tuple[int, str]] = []
        for skill, tokens, skill_name_lower in skill_meta:
            score = 0
            if skill_name_lower in text:
                score += 6
            score += len(tokens & text_tokens)
            if score > 0:
                scored.append((score, skill.name))
        scored.sort(key=lambda x: (-x[0], x[1]))
        for _, skill_name in scored[:4]:
            edges.append((mem_id, skill_name))
    return edges


def build_learning_graph() -> dict[str, Any]:
    """构建完整的学习图谱数据。

    build_learning_graph，返回供前端渲染的完整 payload。

    返回结构:
      {
        "nodes": [{"id", "label", "kind", "category", "useCount", "state", ...}],
        "edges": [{"source", "target"}],
        "clusters": [{"category", "count"}],
        "memory": [{"source", "title", "body", ...}],
        "stats": {...}
      }
    """
    all_skills = build_skill_nodes()
    learned_skills = {
        name: node
        for name, node in all_skills.items()
        if node.source != "preset" and (node.created_by == "agent" or node.use_count > 0)
    }
    skill_edges = build_edges(learned_skills)
    memory_cards = _memory_cards()
    memory_edges = _memory_skill_edges(memory_cards, list(learned_skills.values()))

    edges = skill_edges + memory_edges
    clusters: dict[str, int] = {}
    for node in learned_skills.values():
        clusters[node.category] = clusters.get(node.category, 0) + 1
    if memory_cards:
        clusters["memory"] = len(memory_cards)

    graph_nodes = [
        {
            "id": n.name,
            "label": n.name,
            "kind": "skill",
            "timestamp": n.timestamp,
            "category": n.category,
            "useCount": n.use_count,
            "state": n.state,
            "createdBy": n.created_by,
            "pinned": n.pinned,
        }
        for n in learned_skills.values()
    ]
    for i, card in enumerate(memory_cards):
        graph_nodes.append({
            "id": f"memory:{card['source']}:{i}",
            "label": card["title"],
            "kind": "memory",
            "memorySource": card["source"],
            "timestamp": card.get("timestamp"),
            "category": "memory",
            "useCount": 0,
            "state": "active",
            "createdBy": "memory",
            "pinned": False,
        })

    return {
        "nodes": graph_nodes,
        "edges": [{"source": a, "target": b} for a, b in edges],
        "clusters": [
            {"category": c, "count": n}
            for c, n in sorted(clusters.items(), key=lambda kv: -kv[1])
        ],
        "memory": memory_cards,
        "stats": {
            **density_stats(learned_skills, skill_edges),
            "memory_nodes": len(memory_cards),
            "memory_skill_edges": len(memory_edges),
            "learned_skills": len(learned_skills),
        },
    }
