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
import threading
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from alpha_agent.config import settings
from alpha_agent.core.budget import (
    IterationBudget,
    estimate_messages_tokens_rough,
)
from alpha_agent.infra.catalog import build_catalog_prompt
from alpha_agent.infra.llm import get_llm_service
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

        def _get_guardrail(session_key: str) -> ToolCallGuardrail:
            if session_key not in _guardrail_map:
                _guardrail_map[session_key] = ToolCallGuardrail()
            return _guardrail_map[session_key]

        _approval_config = self._approval_config

        def _get_approval_config():
            return _approval_config

        def agent_node(state: AgentState) -> dict[str, Any]:
            step = state.get("step_count", 0) + 1
            state_max = state.get("max_steps", max_steps)

            logger.info(f"[AgentLoop] 第 {step}/{state_max} 步 | 消息数: {len(state['messages'])}")

            budget_key = f"step_{step}"
            budget = _budget_map.get(budget_key)
            if budget is None:
                budget = IterationBudget(max_iterations=state_max)
                budget.current = step - 1
                _budget_map[budget_key] = budget

            if is_interrupted():
                logger.info("[AgentLoop] 收到中断信号，结束循环")
                return {"messages": [AIMessage(content="[已中断] 分析已被用户中断。")]}

            if not budget.increment():
                return {
                    "messages": [AIMessage(
                        content=f"已达到迭代预算上限 ({budget.max_iterations} 步)。"
                                f"基于已有信息给出最终回答。"
                    )],
                    "step_count": step,
                }

            llm_svc = get_llm_service()
            if not llm_svc.enabled:
                return {
                    "messages": [AIMessage(content="抱歉，LLM 服务未配置，暂时无法提供对话服务。")],
                    "step_count": step,
                }

            guardrail = _get_guardrail(budget_key)

            _update_guardrail_from_history(guardrail, state["messages"])

            context_prefix = _build_context_prefix()
            messages = [SystemMessage(content=context_prefix + system_prompt)] + list(state["messages"])

            tool_failure_hint = _detect_tool_failures(state["messages"])
            if tool_failure_hint:
                messages.append(HumanMessage(content=tool_failure_hint))

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

            if should_strip_tools:
                logger.info(f"[AgentLoop] 第{step}步: 检测到被阻断工具，不带工具调用请求纯文本回答")
                model = llm_svc.model
            else:
                model = llm_svc.model.bind_tools(core_tools)

            response = model.invoke(messages)

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
                            decision = check_all_command_guards(cmd, budget_key, approval_cfg)
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

        def should_continue(state: AgentState) -> str:
            messages = state["messages"]
            last_message = messages[-1]
            step = state.get("step_count", 0)
            state_max = state.get("max_steps", max_steps)

            if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
                logger.info(f"[AgentLoop] 第{step}步: 模型返回纯文本回答，循环结束")
                return END

            if step >= state_max:
                logger.warning(f"[AgentLoop] 达到最大步数 {state_max}，强制结束")
                return "finalize"

            budget_key = f"step_{step}"
            guardrail = _get_guardrail(budget_key)
            all_blocked = True
            for tc in last_message.tool_calls:
                if not guardrail.is_tool_blocked(tc.get("name", "")):
                    all_blocked = False
                    break

            if all_blocked and guardrail.has_blocked_tools:
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

            if consecutive_tool_steps >= 12:
                logger.warning(
                    f"[AgentLoop] 连续 {consecutive_tool_steps} 步仅工具调用无文本输出，强制总结"
                )
                return "finalize"

            return "tools"

        def finalize_node(state: AgentState) -> dict[str, Any]:
            llm_svc = get_llm_service()
            if not llm_svc.enabled:
                return {"messages": [AIMessage(content="抱歉，推理步数超限，未能完成分析。")]}

            messages = [SystemMessage(content=system_prompt)] + list(state["messages"])
            last_step = state.get("step_count", 0)
            guardrail = _get_guardrail(f"step_{last_step}")
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

        graph.set_entry_point("agent")

        graph.add_conditional_edges(
            "agent",
            should_continue,
            {
                "tools": "tools",
                "finalize": "finalize",
                END: END,
            },
        )
        graph.add_edge("tools", "agent")
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
    ):
        self._builder = AgentGraphBuilder(
            system_prompt_override=system_prompt,
            restricted_tool_names=restricted_tool_names,
            max_steps_override=max_steps,
        )

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
        使用 threading 避免阻塞用户响应。
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

            thread = threading.Thread(target=_bg_review, daemon=True)
            thread.start()
        except Exception as e:
            logger.error(f"[LearningLoop] Failed to start background review: {e}")

    def _post_invoke(self, session_id: str, message: str, result: dict) -> None:
        """invoke/stream 后统一后处理。"""
        self._background_review(session_id, message, result)
        self._record_session(session_id, message, result)

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
        for chunk in self.graph.stream(
            {"messages": [HumanMessage(content=message)], "step_count": 0},
            config,
            stream_mode="values",
        ):
            last_result = chunk
            yield chunk

        if last_result is not None:
            self._post_invoke(session_id, message, last_result)

        compressor.on_session_end(session_id)


_agent_loop: AgentLoop | None = None
_agent_loop_lock = threading.Lock()


def get_agent_loop() -> AgentLoop:
    global _agent_loop
    if _agent_loop is None:
        with _agent_loop_lock:
            if _agent_loop is None:
                _agent_loop = AgentLoop()
    return _agent_loop