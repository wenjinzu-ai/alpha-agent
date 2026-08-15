"""AgentLoop —— 单 Agent 持久循环，借鉴 Hermes 的核心架构。

替代 Supervisor + 固定 Worker + 关键词路由。
一个 Agent 拥有全部核心工具，自主决策调用链。

借鉴 Hermes 增强:
  - ContextCompressor: 上下文压缩（PG JSONB）
  - IterationBudget: 迭代预算管理（按会话隔离）
  - Progressive Disclosure: 渐进式技能加载（Tier 1 → Tier 2）
  - SessionStore: PG tsvector 全文搜索
  - Guardrails: 安全护栏

设计：
- AgentGraphBuilder：负责图构建（工具加载、Prompt 组装、LangGraph 编译）
- AgentLoop：负责执行循环（invoke/stream），对 AgentGraphBuilder 的薄封装
"""
from __future__ import annotations

import operator
import re
import threading
import time
import uuid
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, TypedDict

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import RunnableConfig

from alpha_agent.config import settings
from alpha_agent.core.budget import (
    IterationBudget,
    estimate_messages_tokens_rough,
)
from alpha_agent.infra.catalog import build_catalog_prompt
from alpha_agent.infra.llm import get_llm_service
from alpha_agent.infra.process_registry import get_process_registry
from alpha_agent.tools import get_core_tools
from alpha_agent.utils.logger import logger

if TYPE_CHECKING:
    from alpha_agent.core.context_engine import ContextEngine

from alpha_agent.core.approval import (
    ApprovalConfig,
    ApprovalDecision,
    ApprovalMode,
    check_all_command_guards,
)
from alpha_agent.core.interrupt import is_interrupted
from alpha_agent.core.budget_config import BudgetConfig, DEFAULT_BUDGET
from alpha_agent.core.tool_guardrails import (
    ToolCallGuardrailConfig,
    ToolCallGuardrailController,
    ToolGuardrailDecision,
    toolguard_synthetic_result,
    append_toolguard_guidance,
)


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    step_count: int
    max_steps: int


SYSTEM_PROMPT_TEMPLATE = """你是一位专业的投资分析助手，拥有全面的市场数据分析能力。

**核心理念：数据驱动，客观分析，风险优先**

你拥有以下核心能力：

1. **terminal** — 执行任意命令（前台/后台）
   - 前台: terminal("python scripts/sync_stock_kline.py")
   - 后台: terminal("python scripts/sync_stock_kline.py", background=True)
   - 计算因子: terminal("python scripts/calc_stock_factors.py", background=True)
   - 后台任务用 process(action="poll", task_id="...") 查看进度

2. **process** — 管理后台进程
   - poll/wait/list/kill/log 管理后台任务

3. **execute_code** — 执行 Python 代码
   - 预置数据库访问、数据同步服务
   - 多步工作流压缩为一次调用
   - 支持 progress_tracking 进度追踪

4. **execute_pipeline** — 执行预置分析 Pipeline
   - stock_analysis: 个股综合分析（基本面→技术面→风控→报告）
   - stock_screening: 选股（标的池→因子计算→排名筛选）
   - factor_backtest: 因子回测（选股→因子构建→回测→绩效）
   - portfolio_build: 组合构建（选股→权重优化→压力测试）
   - market_overview: 市场概览（行情→行业→资金→异常→报告）
   - data_health_check: 数据健康检查（全表扫描→新鲜度→修复建议）
   - data_auto_repair: 数据自动修复

5. **skill_manage** — 技能生命周期管理（渐进式加载）
   - search: 搜索已有技能，只看元数据（Tier 1）
   - view: 加载完整技能内容（Tier 2），确认需要执行时才用
   - list/patch/edit/fork/retire: 管理技能

6. **delegate_task** — 委派专业子 Agent
   - 指定 profile（fundamental_analyst/technical_analyst/risk_controller/data_engineer/backtest_engineer）
   - 子 Agent 独立执行，通过 process 查看进度

7. **get_database_schema** — 查看数据库表结构（获取 Schema 后用 execute_code 写 SQL 查询）
8. **其他工具**: web_search, generate_chart, detect_anomalies, \
attribute_analysis, manage_alerts, remember, get_current_time

**工作原则：**
- 优先使用 execute_pipeline 执行标准分析流程
- 需要专业分析时使用 delegate_task 委派子 Agent
- 长时间任务（数据同步、批量计算）使用 terminal + background
- 复杂数据操作使用 execute_code（先 get_database_schema 了解表结构，再写 SQL）
- 遇到可复用任务流程，先用 skill_manage(search) 查找已有技能，确认后 skill_manage(view) 加载
- 永远基于真实数据回答，不编造信息
- 永远提示投资风险

**数据查询最佳实践：**
- 先调用 get_database_schema 了解表结构
- 再用 execute_code 编写 SQL 查询（内置 _execute_sql() 函数）
- 查询+分析在同一个 execute_code 中完成，效率最高
- 示例：
  ```python
  schema = get_database_schema()
  result = _execute_sql(\"\"\"
      SELECT trade_date, close FROM daily_kline
      WHERE ts_code = '600519.SH'
      ORDER BY trade_date DESC LIMIT 10
  \"\"\")
  df = pd.DataFrame(result)
  print(df.describe())
  ```

**错误处理：**
- SQL 查询失败 → 检查表名/字段名，重新 get_database_schema
- 同步失败 → 检查数据健康，尝试修复
- 后台任务超时 → process(kill) 终止，分析原因后重试
- 不要连续调用同一工具超过 3 次

{catalog_section}
{user_memory}
"""


class ToolCallGuardrail:
    """工具调用护栏 - 封装 ToolCallGuardrailController。

    支持精确失败、同工具失败、无进展追踪。
    三级响应：allow / warn / halt。
    阻断时生成合成结果 + 恢复提示，引导 LLM 换策略继续。
    """

    def __init__(self):
        self._controller = ToolCallGuardrailController(
            ToolCallGuardrailConfig(
                warnings_enabled=True,
                hard_stop_enabled=True,
                exact_failure_warn_after=2,
                exact_failure_block_after=5,
                same_tool_failure_warn_after=3,
                same_tool_failure_halt_after=8,
                no_progress_warn_after=2,
                no_progress_block_after=5,
            )
        )
        self._halt_decision: ToolGuardrailDecision | None = None

    def before_call(self, tool_name: str, args: dict | None) -> tuple[str, str | None]:
        decision = self._controller.before_call(tool_name, args or {})
        if decision.action == "halt":
            self._halt_decision = decision
            return "block", decision.message
        if decision.action == "warn":
            return "allow", decision.message
        return "allow", None

    def after_call(self, tool_name: str, args: dict | None, failed: bool, result: str | None = None) -> ToolGuardrailDecision | None:
        return self._controller.after_call(
            tool_name=tool_name, args=args or {},
            result=None if failed else (result or ""),
            failed=failed,
        )

    @property
    def has_blocked_tools(self) -> bool:
        return self._controller.has_blocked_tools

    def is_tool_blocked(self, tool_name: str) -> bool:
        return self._controller.is_tool_blocked(tool_name)

    @property
    def halt_decision(self) -> ToolGuardrailDecision | None:
        return self._halt_decision

    def synthetic_result(self) -> str:
        if self._halt_decision:
            return toolguard_synthetic_result(self._halt_decision)
        return "{}"


def _update_guardrail_from_history(guardrail: ToolCallGuardrail, messages: Sequence[BaseMessage]) -> None:
    """从历史消息中提取最近的工具调用结果，更新 guardrail 的失败计数。

    在每步 agent_node 开头调用，确保 guardrail 状态与实际工具结果同步。
    """
    tool_call_args: dict[str, tuple[str, dict | None]] = {}
    for msg in messages:
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tc_id = tc.get("id", "")
                if tc_id:
                    tool_call_args[tc_id] = (tc.get("name", ""), tc.get("args", None))

    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        tc_id = msg.tool_call_id
        if tc_id not in tool_call_args:
            continue
        tool_name, tool_args = tool_call_args[tc_id]
        content = str(msg.content)
        is_failure = any(
            marker in content
            for marker in ["失败", "不可用", "认证失败", "API Key", "请不要", "暂时不可用", "Error", "error"]
        )
        guardrail.after_call(tool_name, tool_args, failed=is_failure, result=(None if is_failure else content))


def _detect_tool_failures(messages: Sequence[BaseMessage]) -> str | None:
    """检测工具连续失败或重复调用，返回提示让 LLM 换策略。

    两种检测：
    1. 同一工具连续失败 >= 2 次 → 提示换工具
    2. 同一工具连续调用 >= 4 次（即使有结果）→ 提示换策略
    """
    recent = messages[-20:] if len(messages) > 20 else list(messages)

    tool_results: dict[str, list[str]] = {}
    tool_call_count: dict[str, int] = {}

    for msg in recent:
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                name = tc.get("name", "")
                if name:
                    tool_call_count[name] = tool_call_count.get(name, 0) + 1

        if not isinstance(msg, ToolMessage):
            continue
        tool_name = msg.name or ""
        content = str(msg.content)

        if tool_name not in tool_results:
            tool_results[tool_name] = []

        is_failure = any(
            marker in content
            for marker in ["失败", "不可用", "认证失败", "API Key", "请不要", "暂时不可用"]
        )
        tool_results[tool_name].append("fail" if is_failure else "ok")

    hints = []
    for tool_name, results in tool_results.items():
        consecutive_fails = 0
        for r in reversed(results):
            if r == "fail":
                consecutive_fails += 1
            else:
                break

        if consecutive_fails >= 2:
            hints.append(
                f"⚠️ 工具 {tool_name} 已连续失败 {consecutive_fails} 次，"
                f"继续调用相同工具不会成功。请立即换用其他工具或基于已有信息回答。"
            )

    for tool_name, count in tool_call_count.items():
        if count >= 4:
            already_hinted = any(tool_name in h for h in hints)
            if not already_hinted:
                hints.append(
                    f"⚠️ 工具 {tool_name} 已被调用 {count} 次，"
                    f"继续搜索不太可能获得更好的结果。"
                    f"请基于已有信息总结回答，或换用其他工具（如 execute_code 查询数据库）。"
                )

    if not hints:
        return None

    return (
        "[系统提示] 检测到工具使用异常：\n"
        + "\n".join(hints)
        + "\n请不要再重复调用相同工具，改用其他方式完成任务。"
    )


MAX_TOOL_RESULT_CHARS = 50000

_review_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="review")


class AgentGraphBuilder:
    """负责构建 LangGraph 图：工具加载、Prompt 组装、Checkpointer 管理、上下文压缩、预算管理。

    借鉴 Hermes 的 ContextCompressor + IterationBudget 架构。
    PG 增强：JSONB 结构化摘要、tsvector 全文搜索。

    Args:
        system_prompt_override: 自定义 system prompt（子 Agent 使用 Profile 的 system_prompt）
        restricted_tool_names: 受限工具名列表（子 Agent 只加载指定工具，去掉 delegate_task 等）
        max_steps_override: 自定义最大步数（子 Agent 使用 Profile 的 max_iterations）
    """

    def __init__(
        self,
        system_prompt_override: str | None = None,
        restricted_tool_names: list[str] | None = None,
        max_steps_override: int | None = None,
        is_child: bool = False,
    ):
        self._core_tools: list[BaseTool] = []
        self._system_prompt: str = ""
        self._checkpointer: PostgresSaver | None = None
        self._pool = None
        self._graph = None
        self._compressor = None
        self._max_steps = max_steps_override or settings.agent_max_steps
        self._system_prompt_override = system_prompt_override
        self._restricted_tool_names = restricted_tool_names
        self._is_child = is_child
        self._approval_config = ApprovalConfig()
        self._budget_config = DEFAULT_BUDGET

    def _ensure_compressor(self) -> ContextEngine:
        if self._compressor is not None:
            return self._compressor
        try:
            from alpha_agent.core.context_compressor import get_context_compressor
            self._compressor = get_context_compressor()
            logger.info("[AgentGraphBuilder] 上下文压缩器已启用")
        except Exception as e:
            logger.warning(f"[AgentGraphBuilder] 上下文压缩器加载失败: {e}")
            from alpha_agent.core.context_engine import NoopContextEngine
            self._compressor = NoopContextEngine()
        return self._compressor

    def _ensure_checkpointer(self) -> PostgresSaver:
        if self._checkpointer is not None:
            return self._checkpointer

        from psycopg_pool import ConnectionPool

        conn_info = (
            f"host={settings.postgres_host} "
            f"port={settings.postgres_port} "
            f"dbname={settings.postgres_db} "
            f"user={settings.postgres_user} "
            f"password={settings.postgres_password}"
        )

        self._pool = ConnectionPool(conninfo=conn_info, min_size=1, max_size=5)
        self._checkpointer = PostgresSaver(self._pool)
        return self._checkpointer

    def close(self) -> None:
        if self._pool is not None:
            try:
                self._pool.close()
            except Exception:
                pass
            self._pool = None

    def cleanup_old_checkpoints(self, session_id: str) -> None:
        checkpointer = self._ensure_checkpointer()
        try:
            with self._pool.connection() as conn:
                conn.execute("""
                    DELETE FROM checkpoints
                    WHERE thread_id = %s
                    AND checkpoint_id NOT IN (
                        SELECT checkpoint_id FROM checkpoints
                        WHERE thread_id = %s
                        ORDER BY checkpoint_id DESC LIMIT 1
                    )
                """, (session_id, session_id))
                conn.commit()
            logger.info(f"[Checkpoint] 清理 session {session_id[:8]} 的旧 checkpoint")
        except Exception as e:
            logger.warning(f"[Checkpoint] 清理失败: {e}")

    def cleanup_expired_sessions(self, max_age_hours: int = 2) -> int:
        checkpointer = self._ensure_checkpointer()
        try:
            with self._pool.connection() as conn:
                result = conn.execute("""
                    DELETE FROM checkpoints
                    WHERE thread_id IN (
                        SELECT DISTINCT thread_id FROM checkpoints
                        GROUP BY thread_id
                        HAVING MAX(checkpoint) IS NOT NULL
                    )
                """)
                conn.commit()
                logger.info(f"[Checkpoint] 全量清理完成")
                return 0
        except Exception as e:
            logger.warning(f"[Checkpoint] 清理过期 session 失败: {e}")
            return 0

    def _ensure_tools_and_prompt(self) -> None:
        if self._core_tools:
            return

        if self._restricted_tool_names is not None:
            from alpha_agent.tools import get_tools_map
            all_tools = get_tools_map()
            self._core_tools = [
                all_tools[name]
                for name in self._restricted_tool_names
                if name in all_tools
            ]
            logger.info(
                f"[AgentGraphBuilder] 受限工具模式: "
                f"{len(self._core_tools)}/{len(self._restricted_tool_names)} 工具已加载"
            )
        else:
            self._core_tools = get_core_tools()

        try:
            from alpha_agent.tools.core.skill_manage import skill_manage
            if self._restricted_tool_names is None or "skill_manage" in self._restricted_tool_names:
                self._core_tools.append(skill_manage)
                logger.info("[AgentGraphBuilder] 渐进式技能加载已启用 (skill_manage)")
        except Exception as e:
            logger.warning(f"[AgentGraphBuilder] skill_manage 加载失败: {e}")

        if self._system_prompt_override is not None:
            self._system_prompt = self._system_prompt_override
        else:
            catalog_section = ""
            try:
                catalog = build_catalog_prompt()
                if catalog:
                    if len(catalog) > 2000:
                        logger.info(f"[AgentGraphBuilder] catalog 截断: {len(catalog)} -> 2000 字符")
                    catalog_section = f"\n**数据地图:**\n{catalog[:2000]}"
            except Exception:
                pass

            user_memory = ""
            try:
                from alpha_agent.infra.memory_store import memory_store
                memory_text = memory_store.get_for_system_prompt()
                if memory_text:
                    user_memory = memory_text
            except Exception:
                pass

            self._system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                catalog_section=catalog_section,
                user_memory=user_memory,
            )

    @staticmethod
    def _messages_to_raw(messages: Sequence[BaseMessage]) -> list[dict[str, str]]:
        """将 LangChain 消息列表转为 dict 列表，供上下文压缩器使用。"""
        raw = []
        for m in messages:
            entry: dict[str, str] = {
                "role": (
                    "system" if isinstance(m, SystemMessage)
                    else "user" if isinstance(m, HumanMessage)
                    else "assistant" if isinstance(m, AIMessage)
                    else "tool"
                ),
                "content": str(m.content),
            }
            if isinstance(m, ToolMessage):
                entry["tool_call_id"] = m.tool_call_id
            raw.append(entry)
        return raw

    @staticmethod
    def _raw_to_messages(raw: list[dict[str, str]]) -> list[BaseMessage]:
        """将 dict 列表还原为 LangChain 消息列表。"""
        result: list[BaseMessage] = []
        for m in raw:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                result.append(SystemMessage(content=content))
            elif role == "assistant":
                result.append(AIMessage(content=content))
            elif role == "tool":
                result.append(ToolMessage(content=content, tool_call_id=m.get("tool_call_id", "")))
            else:
                result.append(HumanMessage(content=content))
        return result

    def build(self):
        """构建并编译 LangGraph 图。幂等：多次调用返回同一实例。"""
        if self._graph is not None:
            return self._graph

        logger.info("[AgentGraphBuilder] 构建 Agent 循环图...")

        self._ensure_tools_and_prompt()
        compressor = self._ensure_compressor()
        max_steps = self._max_steps
        tool_node = ToolNode(self._core_tools)

        core_tools = self._core_tools
        system_prompt = self._system_prompt

        _budget_map: dict[str, IterationBudget] = {}
        _guardrail_map: dict[str, ToolCallGuardrail] = {}
        _approval_config = self._approval_config

        def _get_approval_config():
            return _approval_config

        def _build_context_prefix() -> str:
            now = datetime.now()
            return (
                f"当前时间: {now.strftime('%Y年%m月%d日')} "
                f"星期{['一','二','三','四','五','六','日'][now.weekday()]} "
                f"{now.strftime('%H:%M:%S')}\n\n"
            )

        _TASK_ID_PATTERN = re.compile(r"(?:task_ids?|delegation_ids?)[:\s]+(\S+)")
        _auto_polled_running: set[str] = set()
        _auto_poll_step_counter: dict[str, int] = {}
        _delegate_wait_counter: dict[str, int] = {}
        _delegate_wait_injected: set[str] = set()
        _short_answer_retry: dict[str, int] = {}

        _auto_polled_completed: set[str] = set()

        def _collect_delegate_results() -> list[BaseMessage]:
            """从DelegateRegistry收集已完成的委派子Agent结果，返回ToolMessage列表。

            借鉴Hermes的completion_queue设计：子Agent完成后结果自动注入对话上下文。
            新架构：子Agent在同进程内线程池运行，结果直接从内存获取。
            """
            result_msgs: list[BaseMessage] = []
            try:
                from alpha_agent.tools.core.delegate import DelegateRegistry
                delegate_reg = DelegateRegistry.get()
                completions = delegate_reg.drain_completions()
                for comp in completions:
                    deleg_id = comp.get("delegation_id", "")
                    if deleg_id in _delegate_wait_injected:
                        continue
                    _delegate_wait_injected.add(deleg_id)

                    status = comp.get("status", "unknown")
                    goal = comp.get("goal", "")
                    profile = comp.get("profile", "")
                    result = comp.get("result", "")
                    error = comp.get("error")
                    step_count = comp.get("step_count", 0)
                    tool_count = comp.get("tool_count", 0)
                    duration = comp.get("duration_seconds", 0)

                    status_label = {
                        "completed": "✅完成", "failed": "❌失败",
                    }.get(status, f"❓{status}")

                    parts = [
                        f"[委派子Agent {deleg_id}] {status_label} "
                        f"(Profile: {profile}, 耗时: {duration}s, "
                        f"步数: {step_count}, 工具调用: {tool_count})",
                        f"目标: {goal}",
                    ]

                    if status == "completed" and result:
                        if len(result) > 3000:
                            result = result[:3000] + "\n...(结果过长已截断)"
                        parts.append(f"子Agent分析结果:\n{result}")
                    elif error:
                        parts.append(f"错误信息: {error[:500]}")

                    result_msgs.append(HumanMessage(
                        content=f"[委派子Agent {deleg_id} 完成]\n" + "\n".join(parts)
                    ))
            except Exception as e:
                logger.debug(f"[DelegateWait] 收集委派结果异常: {e}")
            return result_msgs

        def _auto_poll_background_tasks(messages: Sequence[BaseMessage]) -> list[HumanMessage]:
            """自动轮询后台任务和委派子Agent，仅注入已完成任务的结果。

            借鉴Hermes的drain_notifications设计：
            - 子Agent完成后结果自动注入对话上下文（不阻塞主Agent）
            - 运行中的任务不做任何注入，避免LLM陷入反复poll的死循环
            - 同时处理ProcessRegistry后台进程和DelegateRegistry子Agent
            """
            poll_msgs: list[HumanMessage] = []

            try:
                from alpha_agent.tools.core.delegate import DelegateRegistry
                delegate_reg = DelegateRegistry.get()
                completions = delegate_reg.drain_completions()
                for comp in completions:
                    deleg_id = comp.get("delegation_id", "")
                    if deleg_id in _auto_polled_completed:
                        continue
                    _auto_polled_completed.add(deleg_id)

                    status = comp.get("status", "unknown")
                    goal = comp.get("goal", "")
                    profile = comp.get("profile", "")
                    result = comp.get("result", "")
                    error = comp.get("error")
                    step_count = comp.get("step_count", 0)
                    tool_count = comp.get("tool_count", 0)
                    duration = comp.get("duration_seconds", 0)

                    status_emoji = {
                        "completed": "✅", "failed": "❌",
                    }.get(status, "❓")

                    parts = [
                        f"[委派子Agent {deleg_id}] {status_emoji} 已完成 "
                        f"(Profile: {profile}, 耗时: {duration}s, "
                        f"步数: {step_count}, 工具调用: {tool_count})",
                        f"目标: {goal}",
                    ]
                    if status == "completed" and result:
                        if len(result) > 3000:
                            result = result[:3000] + "\n...(结果过长已截断)"
                        parts.append(f"子Agent分析结果:\n{result}")
                    elif error:
                        parts.append(f"错误信息:\n{error[:500]}")

                    poll_msgs.append(HumanMessage(content="\n".join(parts)))
            except Exception:
                pass

            seen_ids: set[str] = set()
            for msg in reversed(messages):
                if isinstance(msg, ToolMessage) and msg.name in (
                    "terminal", "delegate_task", "execute_pipeline",
                ):
                    content = str(msg.content)
                    for m in _TASK_ID_PATTERN.finditer(content):
                        task_id = m.group(1).rstrip(".,;:!?")
                        if task_id in seen_ids or task_id.startswith("deleg_"):
                            continue
                        seen_ids.add(task_id)

                        try:
                            registry = get_process_registry()
                            poll_result = registry.poll(task_id)
                            status = poll_result.get("status", "unknown")

                            if status in ("not_found", "running"):
                                continue

                            if status in ("completed", "failed", "killed", "timeout"):
                                exit_code = poll_result.get("exit_code")
                                full_output = poll_result.get("full_output", "").strip()
                                full_error = poll_result.get("full_error", "").strip()

                                status_emoji = {
                                    "completed": "✅", "failed": "❌",
                                    "killed": "🛑", "timeout": "⏰",
                                }.get(status, "❓")

                                parts = [
                                    f"[后台任务 {task_id}] {status_emoji} 已完成 "
                                    f"(状态: {status}"
                                ]
                                if exit_code is not None:
                                    parts[0] += f", 退出码: {exit_code}"
                                parts[0] += ")"

                                if full_output:
                                    if len(full_output) > 2000:
                                        parts.append(f"输出 (前2000字符):\n{full_output[:2000]}")
                                    else:
                                        parts.append(f"输出:\n{full_output}")
                                if full_error:
                                    parts.append(f"错误:\n{full_error[:500]}")
                                poll_msgs.append(HumanMessage(content="\n".join(parts)))
                        except Exception:
                            pass

            return poll_msgs

        def _check_stuck_delegations(messages: Sequence[BaseMessage]) -> list[HumanMessage]:
            """检测卡住的委派子Agent，通知主Agent可干预。"""
            stuck_msgs: list[HumanMessage] = []
            try:
                from alpha_agent.tools.core.delegate import DelegateRegistry
                delegate_reg = DelegateRegistry.get()
                for r in delegate_reg.list_running():
                    elapsed = time.time() - r.dispatched_at
                    if elapsed > 120:
                        stuck_msgs.append(HumanMessage(
                            content=(
                                f"[系统警告] 子Agent {r.delegation_id} 已运行 {int(elapsed)}s，"
                                f"可能卡住。你可以：\n"
                                f"1. process(action='log', task_id='{r.delegation_id}') 查看日志\n"
                                f"2. process(action='kill', task_id='{r.delegation_id}') 终止\n"
                                f"3. 继续等待它完成"
                            )
                        ))
            except Exception:
                pass

            try:
                registry = get_process_registry()
                stuck_tasks = registry.check_stuck_tasks()
                if stuck_tasks:
                    for s in stuck_tasks[:3]:
                        stuck_msgs.append(HumanMessage(
                            content=(
                                f"[系统警告] 后台任务 {s['task_id']} 已运行 {s['elapsed']}s，"
                                f"可能卡住。你可以：\n"
                                f"1. process(action='log', task_id='{s['task_id']}') 查看日志\n"
                                f"2. process(action='kill', task_id='{s['task_id']}') 终止任务\n"
                                f"3. 继续等待它完成"
                            )
                        ))
            except Exception:
                pass
            return stuck_msgs

        def _get_guardrail(session_key: str) -> ToolCallGuardrail:
            if session_key not in _guardrail_map:
                _guardrail_map[session_key] = ToolCallGuardrail()
            return _guardrail_map[session_key]

        def _wait_for_running_delegations(step: int, state_max: int) -> None:
            if self._is_child:
                return
            try:
                from alpha_agent.tools.core.delegate import DelegateRegistry
                delegate_reg = DelegateRegistry.get()
                running = delegate_reg.list_running()
                if not running:
                    return
                logger.info(
                    f"[AgentLoop] 第{step}步: 有 {len(running)} 个委派子Agent运行中"
                )
            except Exception as e:
                logger.debug(f"[AgentLoop] 委派状态检查异常: {e}")

        def delegate_wait_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
            """委派等待节点：内部循环轮询，定期让主Agent决策。

            借鉴Hermes的async_delegation设计：
            - 子Agent在同进程内线程池运行，通过DelegateRegistry管理
            - 内部循环每3秒检查一次子Agent状态（纯轮询，不调LLM）
            - 每30秒（10轮）退出循环，注入状态摘要，回到agent_node让LLM决策
            - LLM可以：查看日志(process log)、终止子Agent(process kill)、继续等待
            - 所有子Agent完成后，注入ToolMessage结果，回到agent_node综合分析
            - 超时（15分钟）后强制收集结果并终止运行中的子Agent
            """
            from alpha_agent.tools.core.delegate import DelegateRegistry

            thread_id = config.get("configurable", {}).get("thread_id", "default")
            key = f"delegate_wait_{thread_id}"
            max_wait_rounds = 300
            poll_interval = 3
            decision_interval = 10

            wait_count = _delegate_wait_counter.get(key, 0)

            if wait_count >= max_wait_rounds:
                logger.warning(f"[DelegateWait] 等待超过{max_wait_rounds}轮（~{max_wait_rounds * poll_interval // 60}分钟），强制结束")
                _delegate_wait_counter[key] = 0
                result_msgs = _collect_delegate_results()
                result_msgs.append(HumanMessage(
                    content="[系统] 委派任务等待超时（15分钟），以下为已完成的任务结果。"
                    f"仍有运行中的子Agent已被终止。请基于已有信息给出分析。"
                ))
                try:
                    delegate_reg = DelegateRegistry.get()
                    for r in delegate_reg.list_running():
                        delegate_reg.kill(r.delegation_id)
                except Exception:
                    pass
                return {"messages": result_msgs, "step_count": state.get("step_count", 0)}

            delegate_reg = DelegateRegistry.get()

            while True:
                running_records = delegate_reg.list_running()

                if not running_records:
                    logger.info("[DelegateWait] 所有委派子Agent已完成，收集结果")
                    _delegate_wait_counter[key] = 0
                    result_msgs = _collect_delegate_results()
                    if result_msgs:
                        result_msgs.append(HumanMessage(
                            content=(
                                "[系统] *** 所有委派子Agent已完成 ***\n\n"
                                "你必须立即在本次回复中生成完整的最终报告。综合所有子Agent的分析结果，"
                                "整合为一份结构化的综合报告。\n\n"
                                "重要规则：\n"
                                "1. 直接生成完整报告——不要说'现在开始生成'或'我会写报告'之类的空话\n"
                                "2. 包含所有子Agent的关键发现和分析结果，不要遗漏\n"
                                "3. 这是你的最终回复，必须一次性给出完整内容，不会再有机会补充\n"
                                "4. 报告需要包含：执行摘要、详细分析、数据表格、代码示例、结论建议"
                            )
                        ))
                    return {"messages": result_msgs, "step_count": state.get("step_count", 0)}

                wait_count += 1
                _delegate_wait_counter[key] = wait_count
                elapsed_total = wait_count * poll_interval
                logger.info(
                    f"[DelegateWait] 第{wait_count}轮等待，"
                    f"仍有{len(running_records)}个子Agent运行中，"
                    f"已等待{elapsed_total}s"
                )

                time.sleep(poll_interval)

                result_msgs = _collect_delegate_results()

                if wait_count % decision_interval == 0:
                    elapsed_info = []
                    for r in running_records:
                        progress = r.get_progress()
                        elapsed_info.append(
                            f"  - {r.delegation_id} [{progress['profile']}]: "
                            f"已运行{progress['elapsed']}s, "
                            f"步数:{progress['step_count']} 工具:{progress['tool_count']}"
                        )

                    status_summary = (
                        f"[系统] 委派子Agent进度报告（已等待{elapsed_total}s）：\n"
                        f"运行中子Agent ({len(running_records)}个):\n"
                        + "\n".join(elapsed_info) + "\n\n"
                        f"你可以：\n"
                        f"1. process(action='log', task_id='子Agent ID') - 查看某个子Agent的执行日志\n"
                        f"2. process(action='monitor') - 查看所有委派任务详细进度\n"
                        f"3. process(action='kill', task_id='子Agent ID') - 终止某个卡住的子Agent\n"
                        f"4. 直接回复'继续等待' - 系统会继续自动检测\n"
                    )

                    if result_msgs:
                        status_summary = f"[系统] 部分委派子Agent已完成！\n" + status_summary

                    result_msgs.append(HumanMessage(content=status_summary))
                    logger.info(f"[DelegateWait] 第{wait_count}轮，注入状态摘要让主Agent决策")
                    return {"messages": result_msgs, "step_count": state.get("step_count", 0)}

                if result_msgs:
                    still_running = len(running_records) - len(result_msgs)
                    if still_running > 0:
                        result_msgs.append(HumanMessage(
                            content=f"[系统] 部分委派子Agent已完成，仍有{still_running}个运行中。系统会继续等待。"
                        ))
                    return {"messages": result_msgs, "step_count": state.get("step_count", 0)}

                if wait_count >= max_wait_rounds:
                    logger.warning(f"[DelegateWait] 等待超过{max_wait_rounds}轮，强制结束")
                    _delegate_wait_counter[key] = 0
                    result_msgs = _collect_delegate_results()
                    result_msgs.append(HumanMessage(
                        content="[系统] 委派任务等待超时（15分钟），以下为已完成的任务结果。请基于已有信息给出分析。"
                    ))
                    try:
                        for r in delegate_reg.list_running():
                            delegate_reg.kill(r.delegation_id)
                    except Exception:
                        pass
                    return {"messages": result_msgs, "step_count": state.get("step_count", 0)}

        def agent_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
            step = state.get("step_count", 0) + 1
            state_max = state.get("max_steps", max_steps)

            thread_id = config.get("configurable", {}).get("thread_id", "default")
            session_key = f"session_{thread_id}"

            _wait_for_running_delegations(step, state_max)

            logger.info(f"[AgentLoop] 第 {step}/{state_max} 步 | 消息数: {len(state['messages'])}")

            budget = _budget_map.get(session_key)
            if budget is None:
                budget = IterationBudget(max_iterations=state_max)
                _budget_map[session_key] = budget

            if is_interrupted():
                logger.info("[AgentLoop] 收到中断信号，结束循环")
                return {"messages": [AIMessage(content="[已中断] 分析已被用户中断。")]}

            if not budget.increment():
                if budget.extend():
                    logger.info(
                        f"[AgentLoop] 第{step}步: 预算耗尽但检测到有进展，自动续期 "
                        f"(新上限: {budget.max_iterations})"
                    )
                else:
                    return {
                        "messages": [AIMessage(
                            content=(
                                f"已达到迭代预算上限 ({budget.max_iterations} 步)，"
                                f"且最近步骤无新进展，基于已有信息给出最终回答。"
                            )
                        )],
                        "step_count": step,
                    }

            llm_svc = get_llm_service()
            if not llm_svc.enabled:
                return {
                    "messages": [AIMessage(content="抱歉，LLM 服务未配置，暂时无法提供对话服务。")],
                    "step_count": step,
                }

            guardrail = _get_guardrail(session_key)

            _update_guardrail_from_history(guardrail, state["messages"])

            context_prefix = _build_context_prefix()
            messages = [SystemMessage(content=context_prefix + system_prompt)] + list(state["messages"])

            for i, msg in enumerate(messages):
                if isinstance(msg, ToolMessage):
                    content = str(msg.content)
                    if len(content) > MAX_TOOL_RESULT_CHARS:
                        truncated = content[:MAX_TOOL_RESULT_CHARS] + (
                            f"\n\n[结果过长，已截断。原始长度: {len(content)} 字符，"
                            f"显示前 {MAX_TOOL_RESULT_CHARS} 字符]"
                        )
                        messages[i] = ToolMessage(
                            content=truncated,
                            tool_call_id=msg.tool_call_id,
                            name=msg.name,
                        )

            tool_failure_hint = _detect_tool_failures(state["messages"])
            if tool_failure_hint:
                messages.append(HumanMessage(content=tool_failure_hint))

            auto_poll_msgs = _auto_poll_background_tasks(state["messages"])
            for apm in auto_poll_msgs:
                messages.append(apm)

            stuck_msgs = _check_stuck_delegations(state["messages"])
            for sm in stuck_msgs:
                messages.append(sm)

            guardrail_warnings = []
            if guardrail.halt_decision:
                blocked_name = guardrail.halt_decision.tool_name
                guardrail_warnings.append(
                    f"工具 {blocked_name} 已被阻断，不要再调用。"
                )
            if guardrail_warnings:
                messages.append(HumanMessage(
                    content="[系统提示] " + " ".join(guardrail_warnings) + " 请基于已有信息总结回答。"
                ))

            conversation_messages = list(state["messages"])
            raw_conversation = AgentGraphBuilder._messages_to_raw(conversation_messages)

            should_compress = compressor.should_compress_preflight(raw_conversation)
            if not should_compress and len(raw_conversation) > 50:
                estimated = estimate_messages_tokens_rough(raw_conversation)
                logger.warning(
                    f"[ContextCompressor] 消息数 {len(raw_conversation)} 超过安全阈值(50), "
                    f"估算 tokens: {estimated}, 强制触发压缩"
                )
                should_compress = True

            if should_compress:
                estimated = estimate_messages_tokens_rough(raw_conversation)
                logger.info(
                    f"[ContextCompressor] 预检触发压缩 "
                    f"(消息数: {len(raw_conversation)}, 估算 tokens: {estimated})"
                )
                compressed = compressor.compress(raw_conversation, current_tokens=estimated)
                messages = [SystemMessage(content=context_prefix + system_prompt)] + \
                    AgentGraphBuilder._raw_to_messages(compressed)
                logger.info("[ContextCompressor] 压缩完成，已注入摘要到对话上下文")

            should_strip_tools = guardrail.has_blocked_tools and step >= 3

            valid_tool_call_ids: set[str] = set()
            for m in messages:
                if isinstance(m, AIMessage) and hasattr(m, 'tool_calls') and m.tool_calls:
                    for tc in m.tool_calls:
                        tc_id = tc.get("id", "")
                        if tc_id:
                            valid_tool_call_ids.add(tc_id)

            cleaned_messages: list[BaseMessage] = []
            for m in messages:
                if isinstance(m, ToolMessage):
                    if m.tool_call_id not in valid_tool_call_ids:
                        logger.warning(
                            f"[AgentLoop] 第{step}步: 移除孤立ToolMessage "
                            f"(tool_call_id={m.tool_call_id}, name={m.name})"
                        )
                        continue
                    content = m.content
                    if isinstance(content, list):
                        content = "\n".join(
                            block.get("text", str(block))
                            if isinstance(block, dict) else str(block)
                            for block in content
                        )
                        m = ToolMessage(
                            content=content,
                            tool_call_id=m.tool_call_id,
                            name=m.name,
                        )
                cleaned_messages.append(m)
            messages = cleaned_messages

            if should_strip_tools:
                logger.info(f"[AgentLoop] 第{step}步: 检测到被阻断工具，不带工具调用请求纯文本回答")
                model = llm_svc.model
            else:
                model = llm_svc.model.bind_tools(core_tools)

            try:
                response = model.invoke(messages)
            except Exception as e:
                logger.error(
                    f"[AgentLoop] Step {step}: LLM invoke failed: {e}\n"
                    f"Message count: {len(messages)}"
                )
                from langchain_openai.chat_models.base import _convert_message_to_dict
                for i, m in enumerate(messages):
                    try:
                        d = _convert_message_to_dict(m)
                        role = d.get("role", "?")
                        keys = list(d.keys())
                        content_type = type(d.get("content")).__name__
                        content_len = len(str(d.get("content", "")))
                        logger.error(f"  [{i}] {role} keys={keys} content_type={content_type} content_len={content_len}")
                        if role == "tool":
                            logger.error(f"    tool_call_id={d.get('tool_call_id')}")
                        if role == "assistant" and "tool_calls" in d:
                            for tc in d["tool_calls"]:
                                logger.error(f"    tool_call: id={tc.get('id')} name={tc.get('function',{}).get('name')}")
                    except Exception as conv_err:
                        logger.error(f"  [{i}] CONVERSION FAILED: {conv_err}")
                        logger.error(f"    type={type(m).__name__} content_type={type(getattr(m,'content','')).__name__}")
                        if isinstance(m, ToolMessage):
                            logger.error(f"    tool_call_id={m.tool_call_id} name={m.name}")
                raise

            try:
                usage = response.response_metadata.get("token_usage", {})
                if usage:
                    compressor.update_from_response(usage)
            except Exception:
                pass

            tool_count = len(response.tool_calls) if hasattr(response, "tool_calls") else 0

            if tool_count > 0:
                filtered_tool_calls = []
                blocked_names = []
                approval_cfg = _get_approval_config()
                for tc in response.tool_calls:
                    tc_name = tc.get("name", "")
                    tc_args = tc.get("args", {})

                    if tc_name in ("terminal", "execute_code"):
                        cmd = tc_args.get("command", "") or tc_args.get("code", "")
                        if cmd:
                            decision = check_all_command_guards(cmd, thread_id, approval_cfg)
                            if not decision.approved:
                                if decision.require_user:
                                    logger.info(f"[AgentLoop] 第{step}步: 需要用户审批: {decision.reason}")
                                    blocked_names.append(f"{tc_name} (需审批: {decision.reason})")
                                else:
                                    logger.info(f"[AgentLoop] 第{step}步: 审批拒绝: {decision.reason}")
                                    blocked_names.append(f"{tc_name} (已拒绝: {decision.reason})")
                                continue

                    action, warning_msg = guardrail.before_call(tc_name, tc_args)
                    if action == "block":
                        blocked_names.append(tc_name)
                        logger.info(f"[AgentLoop] 第{step}步: 阻断工具调用 {tc_name}")
                    else:
                        filtered_tool_calls.append(tc)

                if blocked_names and not filtered_tool_calls:
                    logger.info(
                        f"[AgentLoop] 第{step}步: 所有工具调用被阻断 [{', '.join(blocked_names)}]，"
                        f"强制请求纯文本回答"
                    )
                    force_summary_prompt = (
                        "你尝试调用的工具已被系统阻断（重复调用过多或连续失败）。"
                        "请基于已获取的信息，直接给出完整的分析回答。"
                        "不要再尝试调用任何工具。"
                    )
                    summary_messages = messages + [
                        response,
                        HumanMessage(content=force_summary_prompt),
                    ]
                    response = llm_svc.model.invoke(summary_messages)
                    tool_count = 0
                elif blocked_names:
                    logger.info(
                        f"[AgentLoop] 第{step}步: 部分工具调用被阻断 [{', '.join(blocked_names)}]，"
                        f"保留 {len(filtered_tool_calls)} 个调用"
                    )
                    response.tool_calls = filtered_tool_calls
                    tool_count = len(filtered_tool_calls)

                if tool_count > 0:
                    tool_names = ", ".join([tc.get("name", "") for tc in response.tool_calls])
                    logger.info(f"[AgentLoop] 第{step}步: 调用工具 [{tool_names}]")
                    for tc in response.tool_calls:
                        budget.record_tool_call(tc.get("name", ""))
            else:
                has_prior_tools = any(
                    hasattr(m, "tool_calls") and m.tool_calls
                    for m in state["messages"]
                    if m.type == "ai"
                )
                if not response.content and has_prior_tools:
                    logger.info(f"[AgentLoop] 第{step}步: 空回答，强制总结")
                    summary_prompt = (
                        "你刚才调用了工具并获得了结果，但没有给出总结。"
                        "请基于工具返回的结果，用中文给出完整的分析回答。"
                        "不要重复原始数据，要提炼关键发现和结论。"
                    )
                    summary_messages = messages + [response, HumanMessage(content=summary_prompt)]
                    response = model.invoke(summary_messages)
                logger.info(f"[AgentLoop] 第{step}步: 生成回答（无工具调用，自然退出）")

            return {"messages": [response], "step_count": step}

        def should_continue(state: AgentState, config: RunnableConfig) -> str:
            messages = state["messages"]
            last_message = messages[-1]
            step = state.get("step_count", 0)
            state_max = state.get("max_steps", max_steps)

            thread_id = config.get("configurable", {}).get("thread_id", "default")
            session_key = f"session_{thread_id}"

            def _has_running_delegates() -> bool:
                if self._is_child:
                    return False
                try:
                    from alpha_agent.tools.core.delegate import DelegateRegistry
                    return len(DelegateRegistry.get().list_running()) > 0
                except Exception:
                    return False

            if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
                if _has_running_delegates():
                    logger.info(
                        f"[AgentLoop] 第{step}步: 有委派子Agent运行中，"
                        f"路由到delegate_wait节点（不调用LLM）"
                    )
                    return "delegate_wait"
                else:
                    key = f"delegate_wait_{thread_id}"
                    if key in _delegate_wait_counter:
                        del _delegate_wait_counter[key]
                    try:
                        from alpha_agent.tools.core.delegate import DelegateRegistry
                        completions = DelegateRegistry.get().drain_completions()
                        if completions:
                            logger.info(
                                f"[AgentLoop] 第{step}步: 有{len(completions)}个委派结果待注入，"
                                f"路由到agent节点收集结果"
                            )
                            return "agent"
                    except Exception:
                        pass

                ai_content = last_message.content if hasattr(last_message, "content") else ""
                if isinstance(ai_content, str) and len(ai_content) < 200:
                    has_delegate_results = any(
                        isinstance(m, HumanMessage) and
                        "[委派子Agent" in str(getattr(m, "content", ""))
                        for m in messages
                    )
                    if has_delegate_results:
                        retry_key = f"short_retry_{thread_id}"
                        retry_count = _short_answer_retry.get(retry_key, 0)
                        if retry_count < 2:
                            _short_answer_retry[retry_key] = retry_count + 1
                            logger.warning(
                                f"[AgentLoop] 第{step}步: 检测到短回答({len(ai_content)}字)"
                                f"且有委派结果，第{retry_count+1}次重试生成完整报告"
                            )
                            return "agent"
                        else:
                            if retry_key in _short_answer_retry:
                                del _short_answer_retry[retry_key]

                logger.info(f"[AgentLoop] 第{step}步: 模型返回纯文本回答，循环结束")
                return END

            if step >= state_max:
                logger.warning(f"[AgentLoop] 达到最大步数 {state_max}，强制结束")
                return "finalize"

            tool_names_in_call = [tc.get("name", "") for tc in last_message.tool_calls]
            delegate_safe_tools = {"delegate_task", "process", "get_current_time"}
            has_non_delegate_tool = any(n not in delegate_safe_tools for n in tool_names_in_call)

            if has_non_delegate_tool and _has_running_delegates():
                logger.info(
                    f"[AgentLoop] 第{step}步: LLM调用非委派工具 {tool_names_in_call}，"
                    f"但有委派子Agent运行中，路由到delegate_wait等待"
                )
                return "delegate_wait"

            guardrail = _get_guardrail(session_key)
            all_blocked = True
            for tc in last_message.tool_calls:
                if not guardrail.is_tool_blocked(tc.get("name", "")):
                    all_blocked = False
                    break

            if all_blocked and guardrail.has_blocked_tools:
                if _has_running_delegates():
                    logger.info(
                        f"[AgentLoop] 第{step}步: 工具被阻断，但有委派子Agent运行中，"
                        f"路由到delegate_wait节点"
                    )
                    return "delegate_wait"
                halt = guardrail.halt_decision
                if halt:
                    logger.info(f"[AgentLoop] 第{step}步: 护栏 halt，生成合成结果: {halt.message}")
                    return "finalize"
                logger.info(f"[AgentLoop] 第{step}步: 所有待调用工具均被阻断，提前结束")
                return END

            consecutive_tool_steps = 0
            for m in reversed(messages):
                if isinstance(m, AIMessage) and hasattr(m, "tool_calls") and m.tool_calls:
                    consecutive_tool_steps += 1
                else:
                    break

            if consecutive_tool_steps >= 15:
                logger.warning(
                    f"[AgentLoop] 连续 {consecutive_tool_steps} 步仅工具调用无文本输出，强制总结"
                )
                return "finalize"

            process_loop_count = 0
            for m in reversed(messages):
                if isinstance(m, AIMessage) and hasattr(m, "tool_calls") and m.tool_calls:
                    names = [tc.get("name", "") for tc in m.tool_calls]
                    if all(n == "process" for n in names):
                        process_loop_count += 1
                    else:
                        break
                else:
                    break
            if process_loop_count >= 3:
                logger.warning(
                    f"[AgentLoop] 连续 {process_loop_count} 步调用 process，强制总结"
                )
                return "finalize"

            recent_process_count = 0
            recent_total = 0
            for m in reversed(messages):
                if isinstance(m, AIMessage) and hasattr(m, "tool_calls") and m.tool_calls:
                    recent_total += 1
                    names = [tc.get("name", "") for tc in m.tool_calls]
                    if any(n == "process" for n in names):
                        recent_process_count += 1
                    if recent_total >= 8:
                        break
                else:
                    break
            if recent_total >= 5 and recent_process_count >= recent_total * 0.6:
                logger.warning(
                    f"[AgentLoop] 最近 {recent_total} 步中 {recent_process_count} 步调用 process，"
                    f"占比过高，强制总结"
                )
                return "finalize"

            return "tools"

        def finalize_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
            llm_svc = get_llm_service()
            if not llm_svc.enabled:
                return {"messages": [AIMessage(content="抱歉，推理步数超限，未能完成分析。")]}

            messages = [SystemMessage(content=system_prompt)] + list(state["messages"])
            last_step = state.get("step_count", 0)
            thread_id = config.get("configurable", {}).get("thread_id", "default")
            session_key = f"session_{thread_id}"
            guardrail = _get_guardrail(session_key)
            if guardrail.halt_decision:
                synt = guardrail.synthetic_result()
                messages.append(HumanMessage(
                    content=f"工具调用被护栏阻止。合成结果: {synt}\n请基于已获取的信息，给出完整的分析回答。"
                ))
            else:
                messages.append(HumanMessage(
                    content="你已达到迭代步数上限。请整理你的最终回答，基于已有信息给出完整分析。"
                    "如果信息不足请如实说明。不要再调用任何工具。"
                ))

            model = llm_svc.model

            logger.info("[AgentLoop] 步数超限，生成最终整理回答（不带工具调用）")
            response = model.invoke(messages)
            return {"messages": [response]}

        graph = StateGraph(AgentState)

        graph.add_node("agent", agent_node)
        graph.add_node("tools", tool_node)
        graph.add_node("finalize", finalize_node)
        graph.add_node("delegate_wait", delegate_wait_node)

        graph.set_entry_point("agent")

        graph.add_conditional_edges(
            "agent",
            should_continue,
            {
                "tools": "tools",
                "finalize": "finalize",
                "agent": "agent",
                "delegate_wait": "delegate_wait",
                END: END,
            },
        )
        graph.add_edge("tools", "agent")
        graph.add_edge("delegate_wait", "agent")
        graph.add_edge("finalize", END)

        checkpointer = self._ensure_checkpointer()
        app = graph.compile(checkpointer=checkpointer)

        logger.info(
            f"[AgentGraphBuilder] 图构建完成 "
            f"(核心工具数: {len(self._core_tools)}, 最大步数: {max_steps})"
        )
        for t in self._core_tools:
            logger.info(f"  - {t.name}")

        self._graph = app
        return app

    @property
    def core_tools(self) -> list[BaseTool]:
        self._ensure_tools_and_prompt()
        return self._core_tools

    @property
    def compressor(self) -> ContextEngine:
        return self._ensure_compressor()


class AgentLoop:
    """Agent 执行循环 —— 对 AgentGraphBuilder 的薄封装。

    借鉴 Hermes 的 conversation_loop 设计：
    - 上下文压缩（ContextCompressor）
    - 迭代预算（IterationBudget，按会话隔离）
    - 后台学习（Background Review）
    - 会话记录（SessionStore，PG tsvector）

    职责单一：提供 invoke() 和 stream() 接口。
    图构建委托给 AgentGraphBuilder。

    Args:
        system_prompt: 自定义 system prompt（子 Agent 使用 Profile 的 system_prompt）
        restricted_tool_names: 受限工具名列表（子 Agent 只加载指定工具，去掉 delegate_task 等）
        max_steps: 自定义最大步数（子 Agent 使用 Profile 的 max_iterations）
    """

    def __init__(
        self,
        system_prompt: str | None = None,
        restricted_tool_names: list[str] | None = None,
        max_steps: int | None = None,
        is_child: bool = False,
    ):
        self._builder = AgentGraphBuilder(
            system_prompt_override=system_prompt,
            restricted_tool_names=restricted_tool_names,
            max_steps_override=max_steps,
            is_child=is_child,
        )
        self._invoke_count = 0

    @property
    def graph(self):
        return self._builder.build()

    def _extract_assistant_text(self, result: dict) -> str:
        """从结果中提取最后的助手回复文本，优先取非工具调用的纯文本回复。"""
        messages = list(result.get("messages", []))
        for m in reversed(messages):
            if isinstance(m, AIMessage):
                if not m.tool_calls:
                    return str(m.content)
                continue
        return ""

    def _record_session(self, session_id: str, message: str, result: dict) -> None:
        """记录会话到 PG（tsvector 全文搜索索引）。"""
        try:
            from alpha_agent.infra.session_store import get_session_store

            assistant_msg = self._extract_assistant_text(result)
            store = get_session_store()
            store.record_turn(
                session_id=session_id,
                user_message=message[:500],
                assistant_message=assistant_msg[:1000],
            )
        except Exception as e:
            logger.debug(f"[SessionStore] 记录跳过: {e}")

    def _background_review(self, session_id: str, message: str, result: dict) -> None:
        """后台触发 Closed Learning Loop，不影响主流程。

        借鉴 Hermes 的 background_review：每轮对话后异步 review。
        使用 ThreadPoolExecutor 避免线程无限增长。
        """
        try:
            messages = list(result.get("messages", []))

            def _bg_review():
                try:
                    from alpha_agent.core.learning_loop import review_and_maybe_learn

                    review_result = review_and_maybe_learn(
                        session_id=session_id,
                        goal=message,
                        messages=[
                            {
                                "role": (
                                    "user" if isinstance(m, HumanMessage)
                                    else "assistant" if isinstance(m, AIMessage)
                                    else "tool"
                                ),
                                "content": str(m.content),
                            }
                            for m in messages
                            if hasattr(m, "content")
                        ],
                    )
                    logger.info(
                        f"[LearningLoop] Session={session_id} "
                        f"score={review_result['total_score']} "
                        f"skill_created={review_result['skill_created']}"
                    )
                except Exception as e:
                    logger.error(f"[LearningLoop] Background review failed: {e}")

            _review_executor.submit(_bg_review)
        except Exception as e:
            logger.error(f"[LearningLoop] Failed to start background review: {e}")

    def _post_invoke(self, session_id: str, message: str, result: dict) -> None:
        """invoke/stream 后统一后处理。"""
        self._background_review(session_id, message, result)
        self._record_session(session_id, message, result)
        self._invoke_count += 1
        if self._invoke_count % 10 == 0:
            try:
                self._builder.cleanup_expired_sessions()
            except Exception:
                pass

    def invoke(self, message: str, session_id: str | None = None) -> dict:
        if session_id is None:
            session_id = str(uuid.uuid4())

        compressor = self._builder._ensure_compressor()
        compressor.on_session_start(session_id)

        config = {"configurable": {"thread_id": session_id}}

        result = self.graph.invoke(
            {"messages": [HumanMessage(content=message)], "step_count": 0},
            config,
        )

        self._post_invoke(session_id, message, result)
        compressor.on_session_end(session_id)
        return result

    def stream(self, message: str, session_id: str | None = None):
        if session_id is None:
            session_id = str(uuid.uuid4())

        compressor = self._builder._ensure_compressor()
        compressor.on_session_start(session_id)

        config = {"configurable": {"thread_id": session_id}}

        last_result = None
        last_final_ai_content_len = 0

        for chunk in self.graph.stream(
            {"messages": [HumanMessage(content=message)], "step_count": 0},
            config,
            stream_mode="values",
        ):
            last_result = chunk
            yield {"mode": "values", "state": chunk}

            messages = chunk.get("messages", []) or []
            if not messages:
                continue
            last_msg = messages[-1]
            if (
                getattr(last_msg, "type", None) == "ai"
                and not bool(getattr(last_msg, "tool_calls", None))
                and isinstance(last_msg.content, str)
                and last_msg.content
            ):
                full = last_msg.content
                if len(full) > last_final_ai_content_len:
                    tail = full[last_final_ai_content_len:]
                    chunk_size = 12
                    for i in range(0, len(tail), chunk_size):
                        piece = tail[i:i + chunk_size]
                        yield {
                            "mode": "messages",
                            "message": AIMessageChunk(content=piece),
                            "metadata": {"step": chunk.get("step_count", 0)},
                        }
                    last_final_ai_content_len = len(full)

        if last_result is not None:
            self._post_invoke(session_id, message, last_result)

        compressor.on_session_end(session_id)

    async def astream(self, message: str, session_id: str | None = None):
        """异步桥接同步 stream()。

        注意：LangGraph MemorySaver checkpointer 暂不实现 async astream 接口，
        所以通过 asyncio.to_thread 把同步 generator 搬到线程池，再产出
        与 stream() 相同的统一结构：
          {"mode": "values", "state": {...}}           — 每步 state 快照
          {"mode": "messages", "message": AIMessageChunk, ...} — 打字机式回答片段
        """
        import queue
        import asyncio

        q: queue.Queue = queue.Queue()
        SENTINEL = object()

        def _worker():
            try:
                for item in self.stream(message, session_id=session_id):
                    q.put(item)
            except Exception as _e:
                q.put({"_error": _e})
            finally:
                q.put(SENTINEL)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

        try:
            loop = asyncio.get_running_loop()
            while True:
                item = await loop.run_in_executor(None, q.get)
                if item is SENTINEL:
                    break
                if isinstance(item, dict) and "_error" in item:
                    raise item["_error"]
                yield item
        finally:
            thread.join(timeout=1.0)


_agent_loop: AgentLoop | None = None
_agent_loop_lock = threading.Lock()


def get_agent_loop() -> AgentLoop:
    global _agent_loop
    if _agent_loop is None:
        with _agent_loop_lock:
            if _agent_loop is None:
                _agent_loop = AgentLoop()
    return _agent_loop