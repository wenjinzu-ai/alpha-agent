"""CLI 统一入口 —— 借鉴 Hermes：一个入口，自然语言驱动一切。

设计原则：
- 所有投资分析能力通过 AgentLoop + 自然语言完成
- 不需要子命令，Agent 自己决定调用什么工具/Pipeline
- 只保留 /tasks /help /clear /exit 四个本地快捷键
"""
import sys
import uuid
from typing import Optional

from alpha_agent.utils.logger import logger


BANNER = r"""
 ___                      _                         _
|_ _|_ __   __ _  ___ _ __| |_ _ __ ___   ___ _ __ | |_
 | || '_ \ / _` |/ _` '__| __| '_ ` _ \ / _ \ '_ \| __|
 | || | | | (_| |  __/ |  | |_| | | | | |  __/ | | | |_
|___|_| |_|\__, |\___|_|   \__|_| |_| |_|\___|_| |_|\__|
           |___/
  智能投顾助手 · AgentLoop 持久循环
  用自然语言提问，Agent 自主完成分析
"""

HELP_TEXT = """
内置命令:
  /help, /h       显示帮助
  /clear, /c      清空对话历史
  /tasks          查看后台任务
  /exit, /quit    退出

使用示例:
  你 > 帮我分析一下平安银行
  你 > 今天市场整体怎么样
  你 > 帮我选5只强势股
  你 > 列出所有可用的技术因子
  你 > 按20日涨跌幅排名
  你 > 行业轮动分析
  你 > 回测一下 000001.SZ 和 600519.SH
  你 > 检查数据健康状态
  你 > 同步K线数据
"""


def _run_interactive():
    """交互模式：启动 AgentLoop，持续对话。"""
    print(BANNER)
    print("🚀 AgentLoop 模式")
    print()

    from alpha_agent.core.agent_loop import get_agent_loop

    agent_loop = get_agent_loop()
    session_id = str(uuid.uuid4())

    print(f"会话: {session_id[:8]}")
    print("你好！我是小投，你的智能投顾助手。有什么可以帮你的？")
    print()

    while True:
        try:
            user_input = input("你 > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n再见！")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            if user_input in ("/exit", "/quit", "/q"):
                print("再见！")
                break
            if user_input in ("/help", "/h"):
                print(HELP_TEXT)
                continue
            if user_input in ("/clear", "/c"):
                session_id = str(uuid.uuid4())
                print(f"已清空对话历史，新会话: {session_id[:8]}")
                continue
            if user_input == "/tasks":
                _show_tasks()
                continue
            print(f"未知命令: {user_input}，输入 /help 查看帮助")
            continue

        print()
        print("小投 > ", end="", flush=True)

        try:
            _stream_agent(agent_loop, session_id, user_input)
        except Exception as e:
            logger.error(f"对话处理失败: {e}")
            print(f"抱歉，处理你的问题时出错了: {e}")
        print()
        print()


def _run_once(message: str):
    """单次查询模式：发送一条消息，流式输出结果后退出。"""
    from alpha_agent.core.agent_loop import get_agent_loop

    agent_loop = get_agent_loop()
    session_id = str(uuid.uuid4())

    _stream_agent(agent_loop, session_id, message)
    print()


def _stream_agent(agent_loop, session_id: str, user_input: str):
    """流式输出 AgentLoop 的响应。"""
    full_response = ""
    in_thinking = False
    tool_count = 0

    for chunk in agent_loop.stream(user_input, session_id=session_id):
        if "messages" in chunk and chunk["messages"]:
            last_msg = chunk["messages"][-1]
            if last_msg.type == "ai":
                if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                    if not in_thinking:
                        print("\n  💭 思考中...", end="", flush=True)
                        in_thinking = True
                    for tc in last_msg.tool_calls:
                        tool_count += 1
                        print(f" 🔧{tc['name']}", end="", flush=True)
                elif last_msg.content:
                    if in_thinking:
                        print(f"\n  ✅ 完成 {tool_count} 次工具调用\n")
                        print("小投 > ", end="", flush=True)
                        in_thinking = False
                    if not full_response:
                        full_response = last_msg.content
                        print(last_msg.content, end="", flush=True)

    if not full_response and in_thinking:
        state = agent_loop.graph.get_state(
            {"configurable": {"thread_id": session_id}}
        )
        messages = state.values.get("messages", [])
        for msg in reversed(messages):
            if msg.type == "ai" and msg.content:
                print()
                print(msg.content)
                break


def _show_tasks():
    """显示后台任务列表。"""
    from alpha_agent.infra.process_registry import get_process_registry

    registry = get_process_registry()
    result = registry.list_tasks()

    total = result.get("total", 0)
    running = result.get("running", 0)
    tasks = result.get("tasks", [])

    if total == 0:
        print("当前没有后台任务")
        return

    print(f"后台任务列表（共{total}个，运行中{running}个）")
    print("-" * 70)
    for t in tasks:
        tid = t.get("task_id", "")
        cmd = t.get("command", "")
        st = t.get("status", "")
        elapsed = t.get("elapsed", 0)
        emoji = {
            "running": "🔄",
            "completed": "✅",
            "failed": "❌",
            "killed": "🛑",
            "timeout": "⏰",
        }.get(st, "⏳")
        print(f"  {emoji} {tid}  [{st}]  {elapsed}s  {cmd}")


def main():
    """统一入口。

    用法:
      python -m alpha_agent.cli              # 交互模式
      python -m alpha_agent.cli "你的问题"    # 单次查询
    """
    if len(sys.argv) > 1:
        message = " ".join(sys.argv[1:])
        _run_once(message)
    else:
        _run_interactive()


if __name__ == "__main__":
    main()