"""delegate_task 工具 —— 动态创建子 Agent，加载 Profile，支持后台模式。

借鉴 Hermes 的 delegate_tool.py 设计：
  - 单任务委派：delegate_task(goal="...", profile="...")
  - 多任务派发（fan-out）：delegate_task(tasks=[...])
  - 后台执行：子 Agent 独立运行，主 Agent 不阻塞
  - 深度限制：子 Agent 不可再 delegate（防无限递归）
  - 受限工具：子 Agent 只加载 Profile 指定的工具，不含 delegate_task

Hermes 参考：
  - tools/delegate_tool.py: delegate_task schema + handler
  - tools/async_delegation.py: 后台子进程管理
"""
import json
import os
from string import Template

from langchain_core.tools import tool

from alpha_agent.config import settings
from alpha_agent.infra.profile_loader import profile_loader
from alpha_agent.utils.executor import run_script_background, write_temp_script
from alpha_agent.utils.logger import logger

MAX_DELEGATE_DEPTH = 2

_FORBIDDEN_TOOLS = {"delegate_task", "skill_manage"}

_SUB_AGENT_SCRIPT = Template('''import json
import sys
import os

sys.path.insert(0, r"$project_root")

from alpha_agent.core.agent_loop import AgentLoop
from alpha_agent.utils.logger import logger

try:
    profile = json.loads(r"""$profile_json""")
    goal = r"""$goal"""
    delegate_depth = $delegate_depth

    system_prompt = profile.get("system_prompt", "")
    tool_names = profile.get("tools", [])
    max_iterations = profile.get("max_iterations", 10)

    if delegate_depth >= $max_depth:
        tool_names = [t for t in tool_names if t != "delegate_task"]

    logger.info(
        f"[SubAgent] Starting: profile={profile.get('name', 'unknown')}, "
        f"tools={tool_names}, max_iterations={max_iterations}, "
        f"depth={delegate_depth}, goal={goal[:100]}"
    )

    agent = AgentLoop(
        system_prompt=system_prompt,
        restricted_tool_names=tool_names,
        max_steps=max_iterations,
    )
    result = agent.invoke(goal)

    messages = result.get("messages", [])
    last_ai = ""
    for msg in reversed(messages):
        if hasattr(msg, "content") and msg.__class__.__name__ == "AIMessage":
            if not getattr(msg, "tool_calls", None):
                last_ai = str(msg.content)
                break

    if last_ai:
        print(last_ai)
    else:
        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.__class__.__name__ == "AIMessage":
                last_ai = str(msg.content)
                break
        if last_ai:
            print(last_ai)
        else:
            print(json.dumps({"status": "completed", "message_count": len(messages)}))

except Exception as e:
    logger.error(f"[SubAgent] Failed: {e}")
    print(json.dumps({"status": "failed", "error": str(e)}))
    sys.exit(1)
''')


@tool
def delegate_task(
    goal: str | None = None,
    profile: str = "general",
    context: str | None = None,
    tasks: list | None = None,
    background: bool = True,
    max_iterations: int = 10,
) -> str:
    """动态创建专业子 Agent，加载 Profile 完成特定任务。

    借鉴 Hermes 的 delegate_task，支持单任务委派和多任务并发派发（fan-out）。

    何时使用：
    - 任务需要专业领域的深入分析（如基本面分析、技术面分析）→ 指定 profile
    - 需要同时执行多个独立分析任务 → 使用 tasks 参数派发
    - 长时间运行的任务，不想阻塞主对话 → 默认后台执行

    可用的 Profile：
    - fundamental_analyst: 基本面分析（估值、财报、盈利能力）
    - technical_analyst: 技术面分析（走势、指标、支撑阻力）
    - risk_controller: 风险控制（仓位、回撤、VaR）
    - data_engineer: 数据工程（同步、清洗、验证）
    - backtest_engineer: 回测工程（策略回测、绩效评估）

    Args:
        goal: 子 Agent 要完成的目标（单任务模式）
        profile: 加载的 Profile 名称
        context: 子 Agent 需要的背景信息（文件路径、错误信息、约束条件等）
        tasks: 多任务列表（多任务模式），每项包含 goal 和可选的 context、profile
        background: 是否后台执行（默认 True）
        max_iterations: 子 Agent 最大迭代步数
    """
    try:
        available = profile_loader.list_profiles()

        if tasks:
            task_ids = []
            task_lines = []
            for t in tasks:
                if isinstance(t, dict):
                    t_goal = t.get("goal", "")
                    t_profile = t.get("profile", profile)
                    t_context = t.get("context", context or "")
                else:
                    t_goal = str(t)
                    t_profile = profile
                    t_context = context or ""

                if not t_goal:
                    continue

                task_id = _delegate_single(
                    goal=t_goal,
                    profile=t_profile,
                    context=t_context,
                    background=background,
                    available=available,
                )
                task_ids.append(task_id)
                task_lines.append(f"  [{t_profile}] {t_goal[:80]}")

            if not task_ids:
                return "错误: tasks 中没有有效的 goal"

            task_desc = "\n".join(task_lines)
            bg_note = "（后台执行，完成后用 process(action='poll', task_id='...') 查看进度）" if background else ""
            return (
                f"🔄 已委派 {len(task_ids)} 个子任务{bg_note}:\n"
                f"{task_desc}\n\n"
                f"task_ids: {', '.join(task_ids)}"
            )

        if not goal:
            return "错误: 需要提供 goal（单任务）或 tasks（多任务）参数"

        task_id = _delegate_single(
            goal=goal,
            profile=profile,
            context=context,
            background=background,
            available=available,
        )
        bg_note = "（后台执行，完成后用 process(action='poll', task_id='...') 查看进度）" if background else ""
        return (
            f"🔄 已委派子任务{bg_note}: [{profile}] {goal[:80]}\n\n"
            f"task_id: {task_id}\n"
            f"子 Agent 以 Profile '{profile}' 独立执行。"
        )

    except Exception as e:
        logger.error(f"delegate_task error: {e}", exc_info=True)
        return f"❌ 委派失败: {e}"


def _delegate_single(
    goal: str,
    profile: str,
    context: str,
    background: bool,
    available: list,
) -> str:
    if profile not in available:
        nearest = _find_nearest(profile, available)
        hint = f" 最接近的: {nearest}" if nearest else ""
        raise ValueError(f"Profile '{profile}' 不存在。可用: {available}{hint}")

    profile_data = profile_loader.load(profile)

    filtered_tools = [t for t in profile_data.get("tools", []) if t not in _FORBIDDEN_TOOLS]
    profile_data = {**profile_data, "tools": filtered_tools}

    enriched_goal = goal
    if context:
        enriched_goal = f"{goal}\n\n背景信息: {context}"

    project_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )

    profile_json = json.dumps(profile_data, ensure_ascii=False)
    goal_escaped = json.dumps(enriched_goal, ensure_ascii=False)

    script_code = _SUB_AGENT_SCRIPT.substitute(
        project_root=project_root.replace("\\", "\\\\"),
        profile_json=profile_json,
        goal=goal_escaped,
        delegate_depth=1,
        max_depth=MAX_DELEGATE_DEPTH,
    )

    script_path = write_temp_script(script_code, prefix="delegate")
    task_id = run_script_background(
        script_path,
        timeout=settings.pipeline_background_timeout,
    )

    logger.info(
        f"[delegate_task] Created sub-agent: task_id={task_id}, "
        f"profile={profile}, tools={filtered_tools}"
    )
    return task_id


def _find_nearest(target: str, candidates: list) -> str | None:
    if not candidates:
        return None
    return min(candidates, key=lambda c: _levenshtein(target, c))


def _levenshtein(a: str, b: str) -> int:
    n, m = len(a), len(b)
    if n > m:
        a, b = b, a
        n, m = m, n
    current = list(range(n + 1))
    for i in range(1, m + 1):
        previous, current = current, [i] + [0] * n
        for j in range(1, n + 1):
            add, delete, change = previous[j] + 1, current[j - 1] + 1, previous[j - 1]
            if a[j - 1] != b[i - 1]:
                change += 1
            current[j] = min(add, delete, change)
    return current[n]
