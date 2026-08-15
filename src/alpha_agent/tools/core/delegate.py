"""delegate_task 工具 —— 动态创建子 Agent，加载 Profile，支持后台模式。

借鉴 Hermes 的 delegate_tool.py 设计：
  - 单任务委派：delegate_task(goal="...", profile="...")
  - 多任务派发（fan-out）：delegate_task(tasks=[...])
  - 后台执行：子 Agent 在线程池中运行，主 Agent 不阻塞
  - 深度限制：子 Agent 不可再 delegate（防无限递归）
  - 受限工具：子 Agent 只加载 Profile 指定的工具，不含 delegate_task

Hermes 参考：
  - tools/delegate_tool.py: delegate_task schema + handler
  - tools/async_delegation.py: 后台线程池管理
  - 子Agent在同进程内运行（AIAgent实例），不是子进程

核心架构变更（vs 旧版）：
  - 旧版：子Agent作为子进程运行（python script.py），通过ProcessRegistry监控
  - 新版：子Agent在同进程内的线程池中运行，通过DelegateRegistry管理
  - 优势：无stdout管道阻塞、无进程间通信问题、结果直接内存返回
  - 主Agent可通过process工具随时查看子Agent日志和进度
"""
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langchain_core.tools import tool

from alpha_agent.config import settings
from alpha_agent.infra.profile_loader import profile_loader
from alpha_agent.utils.logger import logger

MAX_DELEGATE_DEPTH = 2

_FORBIDDEN_TOOLS = {"delegate_task", "skill_manage"}

_CHILD_BLOCKED_TOOLS = frozenset({
    "delegate_task",
    "process",
    "skill_manage",
})

_daemon_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()
_executor_max_workers: int = 0


def _get_executor(max_workers: int) -> ThreadPoolExecutor:
    global _daemon_executor, _executor_max_workers
    with _executor_lock:
        if _daemon_executor is None or max_workers > _executor_max_workers:
            if _daemon_executor is not None:
                _daemon_executor.shutdown(wait=False)
            _daemon_executor = ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix="delegate-worker",
            )
            _executor_max_workers = max_workers
        return _daemon_executor


class SubAgentRecord:
    __slots__ = (
        "delegation_id", "goal", "profile", "context", "status",
        "dispatched_at", "completed_at", "result", "error",
        "step_count", "tool_count", "log_lines", "_lock",
        "_interrupt_requested", "duration_seconds",
    )

    def __init__(self, delegation_id: str, goal: str, profile: str, context: str | None):
        self.delegation_id = delegation_id
        self.goal = goal
        self.profile = profile
        self.context = context
        self.status = "running"
        self.dispatched_at = time.time()
        self.completed_at: float | None = None
        self.result: str | None = None
        self.error: str | None = None
        self.step_count = 0
        self.tool_count = 0
        self.log_lines: list[str] = []
        self._lock = threading.Lock()
        self._interrupt_requested = False
        self.duration_seconds: float = 0.0

    def add_log(self, line: str) -> None:
        with self._lock:
            self.log_lines.append(line)
            if len(self.log_lines) > 500:
                self.log_lines = self.log_lines[-500:]

    def get_log_tail(self, n: int = 20) -> list[str]:
        with self._lock:
            return list(self.log_lines[-n:])

    def get_progress(self) -> dict[str, Any]:
        with self._lock:
            elapsed = time.time() - self.dispatched_at if self.status == "running" else (self.duration_seconds or 0)
            return {
                "delegation_id": self.delegation_id,
                "goal": self.goal[:80],
                "profile": self.profile,
                "status": self.status,
                "elapsed": round(elapsed, 1),
                "step_count": self.step_count,
                "tool_count": self.tool_count,
                "log_lines": len(self.log_lines),
                "error": self.error,
            }

    def mark_completed(self, result: str, step_count: int, tool_count: int) -> None:
        with self._lock:
            self.status = "completed"
            self.completed_at = time.time()
            self.duration_seconds = self.completed_at - self.dispatched_at
            self.result = result
            self.step_count = step_count
            self.tool_count = tool_count

    def mark_failed(self, error: str) -> None:
        with self._lock:
            self.status = "failed"
            self.completed_at = time.time()
            self.duration_seconds = self.completed_at - self.dispatched_at
            self.error = error

    def request_interrupt(self) -> None:
        self._interrupt_requested = True

    @property
    def interrupted(self) -> bool:
        return self._interrupt_requested


class DelegateRegistry:
    _instance: "DelegateRegistry | None" = None

    def __init__(self):
        self._records: dict[str, SubAgentRecord] = {}
        self._lock = threading.Lock()
        self._completion_queue: list[dict] = []

    @classmethod
    def get(cls) -> "DelegateRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, record: SubAgentRecord) -> None:
        with self._lock:
            self._records[record.delegation_id] = record

    def get_record(self, delegation_id: str) -> SubAgentRecord | None:
        with self._lock:
            return self._records.get(delegation_id)

    def list_records(self) -> list[SubAgentRecord]:
        with self._lock:
            return list(self._records.values())

    def list_running(self) -> list[SubAgentRecord]:
        with self._lock:
            return [r for r in self._records.values() if r.status == "running"]

    def list_completed(self) -> list[SubAgentRecord]:
        with self._lock:
            return [r for r in self._records.values() if r.status != "running"]

    def drain_completions(self) -> list[dict]:
        with self._lock:
            results = list(self._completion_queue)
            self._completion_queue.clear()
            return results

    def push_completion(self, record: SubAgentRecord) -> None:
        with self._lock:
            self._completion_queue.append({
                "type": "delegate_completion",
                "delegation_id": record.delegation_id,
                "goal": record.goal[:80],
                "profile": record.profile,
                "status": record.status,
                "result": record.result,
                "error": record.error,
                "step_count": record.step_count,
                "tool_count": record.tool_count,
                "duration_seconds": round(record.duration_seconds, 1),
            })

    def kill(self, delegation_id: str) -> bool:
        with self._lock:
            record = self._records.get(delegation_id)
            if record and record.status == "running":
                record.request_interrupt()
                return True
            return False

    def prune_old(self, max_retained: int = 50) -> None:
        with self._lock:
            completed = [(rid, r) for rid, r in self._records.items() if r.status != "running"]
            if len(completed) <= max_retained:
                return
            completed.sort(key=lambda kv: kv[1].completed_at or 0)
            for rid, _ in completed[:len(completed) - max_retained]:
                del self._records[rid]


def _run_subagent_in_thread(record: SubAgentRecord, profile_data: dict, enriched_goal: str, max_iterations: int) -> None:
    try:
        from alpha_agent.core.agent_loop import AgentLoop
        from alpha_agent.core.approval import ApprovalConfig, ApprovalMode

        system_prompt = profile_data.get("system_prompt", "")
        tool_names = profile_data.get("tools", [])

        blocked = _CHILD_BLOCKED_TOOLS
        tool_names = [t for t in tool_names if t not in blocked]
        if tool_names != profile_data.get("tools", []):
            removed = set(profile_data.get("tools", [])) - set(tool_names)
            record.add_log(f"[SubAgent] 已移除受限工具: {removed}")

        record.add_log(f"[SubAgent] 启动: profile={profile_data.get('name', 'unknown')}, tools={tool_names}, max_steps={max_iterations}")

        agent = AgentLoop(
            system_prompt=system_prompt,
            restricted_tool_names=tool_names,
            max_steps=max_iterations,
            is_child=True,
        )

        step_count = 0
        tool_count = 0
        last_ai = ""

        for chunk in agent.stream(enriched_goal):
            if record.interrupted:
                record.add_log("[SubAgent] 被主Agent终止")
                record.mark_failed("被主Agent终止")
                DelegateRegistry.get().push_completion(record)
                return

            if "messages" in chunk and chunk["messages"]:
                last_msg = chunk["messages"][-1]
                if hasattr(last_msg, "type"):
                    if last_msg.type == "ai":
                        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                            for tc in last_msg.tool_calls:
                                tool_count += 1
                                record.step_count = step_count
                                record.tool_count = tool_count
                                record.add_log(f"[Step {step_count}] 调用工具 {tc.get('name', '?')}")
                        elif last_msg.content:
                            last_ai = str(last_msg.content)
                            step_count += 1
                            record.step_count = step_count
                    elif last_msg.type == "tool":
                        content_preview = str(last_msg.content)[:200].replace("\n", " ")
                        record.add_log(f"[Step {step_count}] 工具返回 - {content_preview}")

        if last_ai:
            record.add_log(f"[SubAgent] 完成: {tool_count} 次工具调用")
            record.mark_completed(last_ai, step_count, tool_count)
        else:
            record.add_log(f"[SubAgent] 完成: {tool_count} 次工具调用，无文本回答")
            record.mark_completed("(无文本回答)", step_count, tool_count)

        DelegateRegistry.get().push_completion(record)
        DelegateRegistry.get().prune_old()

    except Exception as e:
        logger.error(f"[SubAgent] Failed: {e}", exc_info=True)
        record.add_log(f"[SubAgent] 失败: {e}")
        record.mark_failed(str(e))
        DelegateRegistry.get().push_completion(record)


@tool
def delegate_task(
    goal: str | None = None,
    profile: str = "data_engineer",
    context: str | None = None,
    tasks: Any = None,
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

        if isinstance(tasks, str):
            try:
                tasks = json.loads(tasks)
            except (json.JSONDecodeError, TypeError):
                tasks = None

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
                    max_iterations=max_iterations,
                    available=available,
                )
                task_ids.append(task_id)
                task_lines.append(f"  [{t_profile}] {t_goal[:80]}")

            if not task_ids:
                return "错误: tasks 中没有有效的 goal"

            task_desc = "\n".join(task_lines)
            return (
                f"🔄 已委派 {len(task_ids)} 个子任务（后台执行，完成后系统会自动获取结果）:\n"
                f"{task_desc}\n\n"
                f"delegation_ids: {', '.join(task_ids)}\n"
                f"可用 process(action='monitor') 查看进度，process(action='log', task_id='...') 查看日志"
            )

        if not goal:
            return "错误: 需要提供 goal（单任务）或 tasks（多任务）参数"

        task_id = _delegate_single(
            goal=goal,
            profile=profile,
            context=context,
            max_iterations=max_iterations,
            available=available,
        )
        return (
            f"🔄 已委派子任务（后台执行，完成后系统会自动获取结果）: [{profile}] {goal[:80]}\n\n"
            f"delegation_id: {task_id}\n"
            f"可用 process(action='monitor') 查看进度，process(action='log', task_id='{task_id}') 查看日志"
        )

    except Exception as e:
        logger.error(f"delegate_task error: {e}", exc_info=True)
        return f"❌ 委派失败: {e}"


def _delegate_single(
    goal: str,
    profile: str,
    context: str,
    max_iterations: int,
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

    delegation_id = f"deleg_{uuid.uuid4().hex[:8]}"
    record = SubAgentRecord(
        delegation_id=delegation_id,
        goal=goal,
        profile=profile,
        context=context,
    )
    DelegateRegistry.get().register(record)

    executor = _get_executor(max_workers=4)
    executor.submit(
        _run_subagent_in_thread,
        record,
        profile_data,
        enriched_goal,
        max_iterations,
    )

    logger.info(
        f"[delegate_task] Created sub-agent: delegation_id={delegation_id}, "
        f"profile={profile}, tools={filtered_tools}"
    )
    return delegation_id


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