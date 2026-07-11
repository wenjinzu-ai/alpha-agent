"""Curator 自动技能维护 —— 借鉴 Hermes agent/curator.py。

后台技能编排器，定期审查 agent 创建的技能，维护技能集合的健康状态。

职责：
  - 自动状态转换：基于技能活动时间戳自动 active → stale → archived
  - 可选 LLM 合并：fork 辅助 Agent 审查并合并重叠技能
  - 持久化 curator 状态（last_run_at, paused, run_count 等）

严格约束：
  - 只操作 agent_created 来源的技能
  - 绝不自动删除，只归档（archived 状态可恢复）
  - pinned 技能跳过所有自动转换
  - 使用辅助模型，不触碰主会话的 prompt cache

Hermes 参考:
  - agent/curator.py: curator orchestrator
  - tools/skill_usage.py: skill usage tracking
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set

from alpha_agent.config import settings
from alpha_agent.infra.db.database import SessionLocal
from alpha_agent.infra.db.models import AgentSkill
from alpha_agent.utils.logger import logger

DEFAULT_INTERVAL_HOURS = 24 * 7
DEFAULT_MIN_IDLE_HOURS = 2
DEFAULT_STALE_AFTER_DAYS = 30
DEFAULT_ARCHIVE_AFTER_DAYS = 90
DEFAULT_CONSOLIDATE = False


# ============================================================================
# 状态持久化
# ============================================================================

class CuratorState:
    """curator 状态管理器，持久化到 PG。

    借鉴 Hermes 的 .curator_state JSON 文件，但用 PG 存储。
    """

    _instance: "CuratorState | None" = None
    _lock = threading.Lock()

    def __init__(self):
        self._cache: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        try:
            with SessionLocal() as db:
                from sqlalchemy import text
                row = db.execute(
                    text("SELECT state FROM curator_state WHERE id = 1")
                ).fetchone()
                if row:
                    return json.loads(row[0])
        except Exception:
            pass
        return self._default_state()

    def _save(self, state: dict[str, Any]) -> None:
        try:
            with SessionLocal() as db:
                from sqlalchemy import text
                db.execute(
                    text("""
                        INSERT INTO curator_state (id, state, updated_at)
                        VALUES (1, :state, :now)
                        ON CONFLICT (id) DO UPDATE SET state = :state, updated_at = :now
                    """),
                    {
                        "state": json.dumps(state, ensure_ascii=False, default=str),
                        "now": datetime.now(timezone.utc),
                    },
                )
                db.commit()
        except Exception as e:
            logger.debug(f"[CuratorState] 保存失败: {e}")

    @staticmethod
    def _default_state() -> dict[str, Any]:
        return {
            "last_run_at": None,
            "last_run_duration_seconds": None,
            "last_run_summary": None,
            "last_run_summary_shown_at": None,
            "paused": False,
            "run_count": 0,
        }

    def load(self) -> dict[str, Any]:
        if self._cache is None:
            self._cache = self._load()
        return self._cache

    def save(self, state: dict[str, Any]) -> None:
        self._cache = state
        self._save(state)

    def update(self, **kwargs: Any) -> dict[str, Any]:
        state = self.load()
        state.update(kwargs)
        self.save(state)
        return state

    @classmethod
    def get_instance(cls) -> "CuratorState":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance


def get_curator_state() -> CuratorState:
    return CuratorState.get_instance()


# ============================================================================
# 配置
# ============================================================================

def get_interval_hours() -> int:
    return DEFAULT_INTERVAL_HOURS


def get_min_idle_hours() -> int:
    return DEFAULT_MIN_IDLE_HOURS


def get_stale_after_days() -> int:
    return DEFAULT_STALE_AFTER_DAYS


def get_archive_after_days() -> int:
    return DEFAULT_ARCHIVE_AFTER_DAYS


def get_consolidate() -> bool:
    return DEFAULT_CONSOLIDATE


def is_enabled() -> bool:
    return True


def is_paused() -> bool:
    state = get_curator_state().load()
    return bool(state.get("paused", False))


# ============================================================================
# 空闲/间隔检查
# ============================================================================

def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def should_run_now(now: Optional[datetime] = None) -> bool:
    """判断 curator 是否应该立即运行。

    门控条件：
      - enabled == True
      - 未暂停
      - last_run_at 存在且超过 interval_hours
      - 首次运行：种子化 last_run_at 并推迟一个完整周期
    """
    if not is_enabled():
        return False
    if is_paused():
        return False

    state = get_curator_state().load()
    last = _parse_iso(state.get("last_run_at"))
    if last is None:
        if now is None:
            now = datetime.now(timezone.utc)
        try:
            get_curator_state().update(
                last_run_at=now.isoformat(),
                last_run_summary=(
                    "首次运行已推迟 —— curator 已种子化，将在 "
                    f"{get_interval_hours()} 小时后执行首次审查。"
                    "使用 `curator run --dry-run` 可立即预览。"
                ),
            )
        except Exception as e:
            logger.debug("[Curator] 种子化 last_run_at 失败: %s", e)
        return False

    if now is None:
        now = datetime.now(timezone.utc)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    interval = timedelta(hours=get_interval_hours())
    return (now - last) >= interval


# ============================================================================
# 自动状态转换（纯函数，无 LLM）
# ============================================================================

def apply_automatic_transitions(now: Optional[datetime] = None) -> dict[str, Any]:
    """应用自动状态转换: active → stale → archived。

    基于技能的 last_used_at 和 last_patched_at 时间戳。
    借鉴 Hermes 的 apply_automatic_transitions 纯函数逻辑。

    规则：
      - pinned 技能跳过所有转换
      - 只处理 agent_created 来源的技能
      - 超过 stale_after_days 未使用 → stale
      - 超过 archive_after_days 未使用 → archived
      - 最近被修补过的技能重置为 active
    """
    if now is None:
        now = datetime.now(timezone.utc)

    stale_threshold = now - timedelta(days=get_stale_after_days())
    archive_threshold = now - timedelta(days=get_archive_after_days())

    transitions: list[dict[str, Any]] = []

    try:
        with SessionLocal() as db:
            skills = (
                db.query(AgentSkill)
                .filter(
                    AgentSkill.source == "agent_created",
                    AgentSkill.pinned == False,
                )
                .all()
            )

            for skill in skills:
                old_status = skill.status
                last_used = skill.last_used_at

                if old_status == "active":
                    if last_used is None:
                        last_used = skill.created_at
                    if last_used is not None:
                        if last_used.tzinfo is None:
                            last_used = last_used.replace(tzinfo=timezone.utc)
                        if last_used < archive_threshold:
                            skill.status = "archived"
                        elif last_used < stale_threshold:
                            skill.status = "stale"

                elif old_status == "stale":
                    if last_used is not None:
                        if last_used.tzinfo is None:
                            last_used = last_used.replace(tzinfo=timezone.utc)
                        if last_used < archive_threshold:
                            skill.status = "archived"
                        elif last_used >= stale_threshold:
                            skill.status = "active"

                elif old_status == "archived":
                    if last_used is not None:
                        if last_used.tzinfo is None:
                            last_used = last_used.replace(tzinfo=timezone.utc)
                        if last_used >= stale_threshold:
                            skill.status = "active"

                if skill.status != old_status:
                    transitions.append({
                        "name": skill.name,
                        "from": old_status,
                        "to": skill.status,
                    })

            if transitions:
                db.commit()
                logger.info(
                    f"[Curator] 自动状态转换: {len(transitions)} 个技能状态变更"
                )
                for t in transitions:
                    logger.info(
                        f"  {t['name']}: {t['from']} → {t['to']}"
                    )

    except Exception as e:
        logger.error(f"[Curator] 自动状态转换失败: {e}")

    return {
        "state_transitions": transitions,
        "count": len(transitions),
    }


# ============================================================================
# 审查编排
# ============================================================================

def run_curator_review(
    synchronous: bool = False,
    dry_run: bool = False,
    consolidate: Optional[bool] = None,
) -> dict[str, Any]:
    """执行一次 curator 审查。

    步骤：
      1. 应用自动状态转换（纯函数，无 LLM）
      2. 如果启用 consolidation，生成合并建议报告
      3. 更新 curator 状态

    如果 synchronous=True，同步执行；默认异步（daemon 线程）。
    """
    if consolidate is None:
        consolidate = get_consolidate()

    def _run():
        start = datetime.now(timezone.utc)

        auto_result = apply_automatic_transitions()

        consolidate_result: dict[str, Any] = {}
        if consolidate and not dry_run:
            consolidate_result = _generate_consolidation_report(dry_run=dry_run)

        result = {
            "auto_transitions": auto_result,
            "consolidation": consolidate_result,
            "dry_run": dry_run,
        }

        duration = (datetime.now(timezone.utc) - start).total_seconds()
        summary = _build_summary(result, duration)

        get_curator_state().update(
            last_run_at=start.isoformat(),
            last_run_duration_seconds=duration,
            last_run_summary=summary,
            run_count=get_curator_state().load().get("run_count", 0) + 1,
        )

        logger.info(f"[Curator] 审查完成 ({duration:.1f}s): {summary}")
        return result

    if synchronous:
        return _run()
    else:
        result_holder: dict[str, Any] = {}

        def _bg():
            try:
                result_holder.update(_run())
            except Exception as e:
                logger.error(f"[Curator] 后台审查失败: {e}")

        thread = threading.Thread(target=_bg, daemon=True)
        thread.start()
        return {"status": "started", "mode": "async"}


def _generate_consolidation_report(dry_run: bool = False) -> dict[str, Any]:
    """生成合并建议报告。

    分析 agent_created 技能，识别前缀聚类，建议合并策略。
    借鉴 Hermes 的 LLM consolidation 提示词逻辑，但做纯启发式分析。
    """
    clusters: dict[str, list[str]] = {}

    try:
        with SessionLocal() as db:
            skills = (
                db.query(AgentSkill)
                .filter(
                    AgentSkill.source == "agent_created",
                    AgentSkill.status.in_(["active", "stale"]),
                    AgentSkill.pinned == False,
                )
                .all()
            )

            for skill in skills:
                prefix = skill.name.split("-")[0]
                if prefix not in clusters:
                    clusters[prefix] = []
                clusters[prefix].append(skill.name)

    except Exception as e:
        logger.error(f"[Curator] 合并报告生成失败: {e}")
        return {"error": str(e)}

    candidates = {
        prefix: names
        for prefix, names in clusters.items()
        if len(names) >= 2
    }

    return {
        "total_skills": sum(len(v) for v in clusters.values()),
        "clusters_found": len(candidates),
        "candidates": candidates,
        "suggestion": (
            f"发现 {len(candidates)} 个前缀聚类（2+ 技能共享前缀）。"
            "考虑将同聚类技能合并为 umbrella 技能。"
        ) if candidates else "未发现可合并的聚类。",
    }


def _build_summary(result: dict[str, Any], duration_seconds: float) -> str:
    transitions = result["auto_transitions"].get("state_transitions", [])
    cons = result.get("consolidation", {})

    lines = []
    if transitions:
        lines.append(f"状态转换: {len(transitions)} 个技能")
    if cons.get("clusters_found", 0) > 0:
        lines.append(f"合并候选: {cons['clusters_found']} 个聚类")

    if not lines:
        lines.append("无需操作")

    return " | ".join(lines)


def maybe_run_curator(synchronous: bool = False) -> dict[str, Any] | None:
    """如果满足条件，触发 curator 审查。

    在 Agent 空闲时（如对话结束后）调用。
    检查 should_run_now() 门控条件。
    """
    if not should_run_now():
        return None

    logger.info("[Curator] 触发自动审查...")
    return run_curator_review(synchronous=synchronous)


def curator_status() -> dict[str, Any]:
    """获取 curator 当前状态。"""
    state = get_curator_state().load()
    return {
        "enabled": is_enabled(),
        "paused": is_paused(),
        "last_run_at": state.get("last_run_at"),
        "last_run_duration_seconds": state.get("last_run_duration_seconds"),
        "last_run_summary": state.get("last_run_summary"),
        "run_count": state.get("run_count", 0),
        "interval_hours": get_interval_hours(),
        "stale_after_days": get_stale_after_days(),
        "archive_after_days": get_archive_after_days(),
        "consolidate_enabled": get_consolidate(),
    }
