"""Closed Learning Loop —— 每轮对话后后台 fork 重放，评分规则判断是否沉淀 Skill。

learning_graph.py 和 background_review.py 设计：
  - 对话结束后，后台 fork 一个新 Agent 来分析对话质量
  - 根据评分规则判断是否值得沉淀为 Skill
  - 采用 LangGraph StateGraph 构建学习循环

评分规则 (review_prompt)：
  1. 任务完成度：是否完成了用户要求？（0-100）
  2. 效率：是否有不必要的步骤？（0-100）
  3. 可复用性：这个任务流程是否可以复用？（0-100）
  4. 创新性：是否有新的、有价值的模式？（0-100）

沉淀条件：
  - 总分 >= 250 且 可复用性 >= 70 → 自动沉淀
  - 总分 >= 200 且 可复用性 >= 85 → 建议沉淀（把结果给用户确认）
"""
from typing import Any, Dict, List, Optional, TypedDict

from pydantic import BaseModel, Field

from alpha_agent.config import settings
from alpha_agent.infra.memory_store import memory_store
from alpha_agent.infra.skill_store import skill_store
from alpha_agent.utils.logger import logger


class ReviewScore(BaseModel):
    """Review 评分结果。"""
    task_completion: int = Field(default=0, ge=0, le=100, description="任务完成度")
    efficiency: int = Field(default=0, ge=0, le=100, description="效率评分")
    reusability: int = Field(default=0, ge=0, le=100, description="可复用性")
    innovation: int = Field(default=0, ge=0, le=100, description="创新性")
    total: int = Field(default=0, description="总分")
    should_create_skill: bool = Field(default=False, description="是否应该沉淀技能")
    skill_name_hint: str = Field(default="", description="建议的技能名称")
    skill_description: str = Field(default="", description="建议的技能描述")
    summary: str = Field(default="", description="评分摘要")


class LearningLoopResult(TypedDict):
    """学习循环结果。"""
    session_id: str
    total_score: int
    skill_created: bool
    skill_name: str
    memory_consolidated: bool
    summary: str


def calculate_score_from_metrics(metrics: Dict[str, Any]) -> Optional[ReviewScore]:
    """根据对话指标计算评分。无有效 metrics 时返回 None，跳过评分。

    review_prompt 评分逻辑。
    """
    if not metrics:
        return None

    task_completion = metrics.get("task_completion")
    efficiency = metrics.get("efficiency")
    reusability = metrics.get("reusability")
    innovation = metrics.get("innovation")

    if task_completion is None and efficiency is None and reusability is None:
        return None

    tc = int(task_completion) if task_completion is not None else 0
    ef = int(efficiency) if efficiency is not None else 0
    ru = int(reusability) if reusability is not None else 0
    iv = int(innovation) if innovation is not None else 0

    total = tc + ef + ru + iv

    should_create = (
        (total >= 250 and ru >= 70) or
        (total >= 200 and ru >= 85)
    )

    return ReviewScore(
        task_completion=tc,
        efficiency=ef,
        reusability=ru,
        innovation=iv,
        total=total,
        should_create_skill=should_create,
        skill_name_hint=metrics.get("skill_name_hint", ""),
        skill_description=metrics.get("skill_description", ""),
        summary=metrics.get("summary", ""),
    )


def extract_tool_sequence(conversation_history: List[Dict]) -> List[Dict]:
    """从对话 history 中提取工具调用序列。

    tool_call_aggregator，分析 Agent 执行模式。
    """
    tool_calls = []
    for msg in conversation_history:
        if msg.get("role") == "tool":
            tool_calls.append({
                "name": msg.get("name", "unknown"),
                "content": str(msg.get("content", ""))[:200],
            })
    return tool_calls


def generate_skill_name(goal: str, tool_sequence: List[Dict]) -> str:
    """根据目标和工具调用生成技能名称。使用 session_id 确保唯一性。"""
    keywords = []
    for tc in tool_sequence:
        name = tc.get("name", "")
        if name in ("get_database_schema",):
            if "data" not in keywords:
                keywords.append("data")
        elif name in ("terminal", "execute_code"):
            if "exec" not in keywords:
                keywords.append("exec")
        elif name in ("execute_pipeline",):
            if "pipeline" not in keywords:
                keywords.append("pipeline")
        elif name in ("web_search",):
            if "search" not in keywords:
                keywords.append("search")
        elif name in ("generate_chart",):
            if "chart" not in keywords:
                keywords.append("chart")

    if not keywords:
        keywords = ["task"]

    import uuid
    short_id = uuid.uuid4().hex[:8]
    return f"{'-'.join(keywords[:3])}-{short_id}"


def generate_skill_content(
    goal: str,
    tool_sequence: List[Dict],
    score: ReviewScore,
    session_id: str,
) -> str:
    """生成技能内容（SKILL.md 格式）。

    SKILL.md 格式。
    """
    tool_steps = "\n".join([
        f"  {i+1}. 调用 `{tc['name']}` 工具"
        for i, tc in enumerate(tool_sequence[:10])
    ])

    return f"""# {score.skill_name_hint or 'agent-skill'}

**目标：** {goal}

**评分：** 完成度={score.task_completion} 效率={score.efficiency} 可复用性={score.reusability} 创新性={score.innovation}

**来源：** 自动生成（session={session_id}）

## 执行步骤

{tool_steps}

## 注意事项

- 此技能由 Agent 自动沉淀，可能需要手动审查和优化
- 使用 `skill_manage(action="edit", name="...")` 修改内容
- 使用 `skill_manage(action="retire", name="...")` 退役
"""


def run_review_loop(
    session_id: str,
    goal: str,
    conversation_history: List[Dict],
    metrics: Optional[Dict[str, Any]] = None,
) -> LearningLoopResult:
    """执行 Closed Learning Loop。

    1. 分析对话历史，提取工具调用序列
    2. 根据评分规则评估是否沉淀
    3. 满足条件则创建 Skill 并记录记忆
    """
    logger.info(f"[LearningLoop] Starting review for session={session_id}")

    tool_sequence = extract_tool_sequence(conversation_history)

    score = calculate_score_from_metrics(metrics or {})

    skill_name = ""
    skill_created = False
    memory_consolidated = False

    if score is None:
        logger.info(f"[LearningLoop] No metrics provided, skipping scoring. Recording basic episodic memory.")
        try:
            memory_store.add(
                content=f"对话: {goal[:200]}",
                layer="episodic",
                session_id=session_id,
                tags=["conversation"],
                importance=0.3,
                summary=goal[:100],
                source="conversation",
                ttl_days=30,
            )
            memory_consolidated = True
        except Exception as e:
            logger.error(f"[LearningLoop] Failed to save basic memory: {e}")

        result: LearningLoopResult = {
            "session_id": session_id,
            "total_score": 0,
            "skill_created": False,
            "skill_name": "",
            "memory_consolidated": memory_consolidated,
            "summary": "无评分指标，仅记录对话记忆",
        }
        return result

    if score.should_create_skill:
        skill_name = score.skill_name_hint or generate_skill_name(goal, tool_sequence)

        try:
            existing = skill_store.get_skill(skill_name)
            if existing:
                logger.info(f"[LearningLoop] Skill '{skill_name}' already exists, skipping")
            else:
                content = generate_skill_content(goal, tool_sequence, score, session_id)
                trigger_keywords = goal.lower().split()[:5]

                skill_store.create_skill(
                    name=skill_name,
                    content=content,
                    category="auto-generated",
                    description=score.skill_description or f"自动沉淀: {goal[:100]}",
                    trigger_keywords=trigger_keywords,
                    metadata={
                        "source_session": session_id,
                        "score": score.model_dump(),
                        "tool_count": len(tool_sequence),
                    },
                    source="agent_created",
                    created_by="learning_loop",
                )
                skill_created = True
                logger.info(f"[LearningLoop] Skill created: {skill_name} (total_score={score.total})")
        except Exception as e:
            logger.error(f"[LearningLoop] Failed to create skill: {e}")

    try:
        score_summary = (
            f"完成度={score.task_completion} 效率={score.efficiency} "
            f"可复用性={score.reusability} 创新性={score.innovation} "
            f"总分={score.total}"
        )
        memory_store.add(
            content=f"任务: {goal}\n评分: {score_summary}",
            layer="episodic",
            session_id=session_id,
            tags=["review", "auto"] + (["skill_created"] if skill_created else []),
            importance=min(score.total / 400.0, 1.0),
            summary=f"Review [{score.total}分]: {goal[:100]}",
            metadata={
                "score": score.model_dump(),
                "skill_created": skill_created,
                "skill_name": skill_name,
            },
            source="review_loop",
            ttl_days=90,
        )
        memory_consolidated = True
    except Exception as e:
        logger.error(f"[LearningLoop] Failed to save memory: {e}")

    result: LearningLoopResult = {
        "session_id": session_id,
        "total_score": score.total,
        "skill_created": skill_created,
        "skill_name": skill_name,
        "memory_consolidated": memory_consolidated,
        "summary": score.summary,
    }
    logger.info(f"[LearningLoop] Review complete: {result}")
    return result


def review_and_maybe_learn(
    session_id: str,
    goal: str,
    messages: Optional[List[Dict]] = None,
    metrics: Optional[Dict[str, Any]] = None,
) -> LearningLoopResult:
    """review_and_maybe_learn —— 对一次对话进行 Review，满足条件则沉淀 Skill。

    background_review.py 的入口函数。
    """
    if messages is None:
        messages = []

    return run_review_loop(
        session_id=session_id,
        goal=goal,
        conversation_history=messages,
        metrics=metrics,
    )