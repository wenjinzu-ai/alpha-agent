"""AgentLoop —— 单 Agent 持久循环，借鉴 Hermes 的核心架构。

替代 Supervisor + 固定 Worker + 关键词路由。
一个 Agent 拥有全部核心工具，自主决策调用链。

设计：
- AgentGraphBuilder：负责图构建（工具加载、Prompt 组装、LangGraph 编译）
- AgentLoop：负责执行循环（invoke/stream），对 AgentGraphBuilder 的薄封装
"""
import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime

from langchain_core.tools import BaseTool
from langchain_core.messages import (
    BaseMessage, HumanMessage, AIMessage, SystemMessage,
)
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.postgres import PostgresSaver
import operator
from typing import TypedDict, Annotated, Sequence

from alpha_agent.infra.llm import get_llm_service
from alpha_agent.tools import get_core_tools
from alpha_agent.infra.catalog import build_catalog_prompt
from alpha_agent.config import settings
from alpha_agent.utils.logger import logger


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

5. **skill_manage** — 技能生命周期管理
   - search: 搜索已有技能，复用成熟方案
   - create: 沉淀新的可复用技能
   - list/patch/edit/fork/retire: 管理技能

6. **delegate_task** — 委派专业子 Agent
   - 指定 profile（fundamental_analyst/technical_analyst/risk_controller/data_engineer/backtest_engineer）
   - 子 Agent 独立执行，通过 process 查看进度

7. **get_database_schema** — 查看数据库表结构（获取 Schema 后用 execute_code 写 SQL 查询）
8. **其他工具**: web_search, generate_chart, detect_anomalies, attribute_analysis, manage_alerts, remember, get_current_time

**工作原则：**
- 优先使用 execute_pipeline 执行标准分析流程
- 需要专业分析时使用 delegate_task 委派子 Agent
- 长时间任务（数据同步、批量计算）使用 terminal + background
- 复杂数据操作使用 execute_code（先 get_database_schema 了解表结构，再写 SQL）
- 遇到可复用任务流程，使用 skill_manage 搜索或沉淀为技能
- 永远基于真实数据回答，不编造信息
- 永远提示投资风险

**数据查询最佳实践：**
- 先调用 get_database_schema 了解表结构
- 再用 execute_code 编写 SQL 查询（内置 _execute_sql() 函数）
- 查询+分析在同一个 execute_code 中完成，效率最高
- 示例：
  ```python
  schema = get_database_schema()
  # 直接用 execute_code：
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


def _format_system_prompt(catalog_section: str = "", user_memory: str = "") -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        catalog_section=catalog_section,
        user_memory=user_memory,
    )


class AgentGraphBuilder:
    """负责构建 LangGraph 图：工具加载、Prompt 组装、Checkpointer 管理、图编译。

    将 AgentLoop 的图构建逻辑提取为独立类，遵循 SRP。
    AgentLoop 只负责执行，AgentGraphBuilder 负责构建。
    """

    def __init__(self):
        self._core_tools: List[BaseTool] = []
        self._system_prompt: str = ""
        self._checkpointer: Optional[PostgresSaver] = None
        self._graph = None

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

        pool = ConnectionPool(conninfo=conn_info, min_size=1, max_size=5)
        self._checkpointer = PostgresSaver(pool)
        return self._checkpointer

    def _ensure_tools_and_prompt(self):
        if self._core_tools:
            return

        self._core_tools = get_core_tools()

        catalog_section = ""
        try:
            catalog = build_catalog_prompt()
            if catalog:
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

        self._system_prompt = _format_system_prompt(catalog_section, user_memory)

    def build(self):
        """构建并编译 LangGraph 图。幂等：多次调用返回同一实例。"""
        if self._graph is not None:
            return self._graph

        logger.info("[AgentGraphBuilder] 构建 Agent 循环图...")

        self._ensure_tools_and_prompt()
        max_steps = settings.agent_max_steps
        tool_node = ToolNode(self._core_tools)

        core_tools = self._core_tools
        system_prompt = self._system_prompt

        def agent_node(state: AgentState) -> Dict[str, Any]:
            step = state.get("step_count", 0) + 1
            state_max = state.get("max_steps", max_steps)

            logger.info(f"[AgentLoop] 第 {step}/{state_max} 步 | 消息数: {len(state['messages'])}")

            llm_svc = get_llm_service()
            if not llm_svc.enabled:
                return {
                    "messages": [AIMessage(content="抱歉，LLM 服务未配置，暂时无法提供对话服务。")],
                    "step_count": step,
                }

            now = datetime.now()
            date_str = now.strftime("%Y年%m月%d日")
            time_str = now.strftime("%H:%M:%S")
            weekday = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
            context_prefix = f"当前时间: {date_str} 星期{weekday} {time_str}\n\n"

            messages = [SystemMessage(content=context_prefix + system_prompt)] + list(state["messages"])

            model = llm_svc.model.bind_tools(core_tools)
            response = model.invoke(messages)

            tool_count = len(response.tool_calls) if hasattr(response, "tool_calls") else 0

            if tool_count > 0:
                tool_names = ", ".join([tc.get("name", "") for tc in response.tool_calls])
                logger.info(f"[AgentLoop] 第{step}步: 调用工具 [{tool_names}]")
            else:
                logger.info(f"[AgentLoop] 第{step}步: 生成回答")

            return {"messages": [response], "step_count": step}

        def should_continue(state: AgentState) -> str:
            messages = state["messages"]
            last_message = messages[-1]
            step = state.get("step_count", 0)
            state_max = state.get("max_steps", max_steps)

            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                if step >= state_max:
                    logger.warning(f"[AgentLoop] 达到最大步数 {state_max}，强制结束")
                    return "finalize"
                return "tools"

            return END

        def finalize_node(state: AgentState) -> Dict[str, Any]:
            llm_svc = get_llm_service()
            if not llm_svc.enabled:
                return {"messages": [AIMessage(content="抱歉，推理步数超限，未能完成分析。")]}

            messages = [SystemMessage(content=system_prompt)] + list(state["messages"])
            messages.append(HumanMessage(content="请整理你的最终回答。基于已有信息给出完整分析，如果信息不足请如实说明。"))

            model = llm_svc.model.bind_tools(core_tools)
            response = model.invoke(messages)

            logger.info("[AgentLoop] 步数超限，生成最终整理回答")
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

        logger.info(f"[AgentGraphBuilder] 图构建完成 (核心工具数: {len(self._core_tools)}, 最大步数: {max_steps})")
        for t in self._core_tools:
            logger.info(f"  - {t.name}")

        self._graph = app
        return app

    @property
    def core_tools(self) -> List[BaseTool]:
        self._ensure_tools_and_prompt()
        return self._core_tools


class AgentLoop:
    """Agent 执行循环 —— 对 AgentGraphBuilder 的薄封装。

    职责单一：提供 invoke() 和 stream() 接口。
    图构建委托给 AgentGraphBuilder。
    """

    def __init__(self):
        self._builder = AgentGraphBuilder()

    @property
    def graph(self):
        return self._builder.build()

    def invoke(self, message: str, session_id: Optional[str] = None) -> dict:
        if session_id is None:
            session_id = str(uuid.uuid4())

        config = {"configurable": {"thread_id": session_id}}

        result = self.graph.invoke(
            {"messages": [HumanMessage(content=message)], "step_count": 0},
            config,
        )

        self._background_review(session_id, message, result)
        return result

    def _background_review(self, session_id: str, message: str, result: dict):
        """后台触发 Closed Learning Loop，不影响主流程。

        借鉴 Hermes 的 background_review：每轮对话后异步 review。
        使用 threading 避免阻塞用户响应。
        """
        try:
            import threading

            messages = list(result.get("messages", []))

            def _bg_review():
                try:
                    from alpha_agent.core.learning_loop import review_and_maybe_learn

                    review_result = review_and_maybe_learn(
                        session_id=session_id,
                        goal=message,
                        messages=[
                            {"role": "user" if isinstance(m, HumanMessage) else "assistant" if isinstance(m, AIMessage) else "tool", "content": str(m.content)}
                            for m in messages
                            if hasattr(m, "content")
                        ],
                    )
                    logger.info(f"[LearningLoop] Session={session_id} score={review_result['total_score']} "
                                f"skill_created={review_result['skill_created']}")
                except Exception as e:
                    logger.error(f"[LearningLoop] Background review failed: {e}")

            thread = threading.Thread(target=_bg_review, daemon=True)
            thread.start()
        except Exception as e:
            logger.error(f"[LearningLoop] Failed to start background review: {e}")

    def stream(self, message: str, session_id: Optional[str] = None):
        if session_id is None:
            session_id = str(uuid.uuid4())

        config = {"configurable": {"thread_id": session_id}}

        for chunk in self.graph.stream(
            {"messages": [HumanMessage(content=message)], "step_count": 0},
            config,
            stream_mode="values",
        ):
            yield chunk


_agent_loop: Optional[AgentLoop] = None


def get_agent_loop() -> AgentLoop:
    global _agent_loop
    if _agent_loop is None:
        _agent_loop = AgentLoop()
    return _agent_loop