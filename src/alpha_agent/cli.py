"""CLI 统一入口 - 借鉴 Hermes：一个入口，自然语言驱动一切。

设计原则：
- 所有投资分析能力通过 AgentLoop + 自然语言完成
- 不需要子命令，Agent 自己决定调用什么工具/Pipeline
- 只保留 /tasks /help /clear /exit 四个本地快捷键
"""
import sys
import uuid
from datetime import datetime

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.markdown import Markdown
from rich.live import Live
from rich.align import Align
from rich import box

from alpha_agent.utils.logger import logger

console = Console()

BANNER = r"""
 ___                      _                         _
|_ _|_ __   __ _  ___ _ __| |_ _ __ ___   ___ _ __ | |_
 | || '_ \ / _` |/ _` '__| __| '_ ` _ \ / _ \ '_ \| __|
 | || | | | (_| |  __/ |  | |_| | | | | |  __/ | | | |_
|___|_| |_|\__, |\___|_|   \__|_| |_| |_|\___|_| |_|\__|
           |___/
"""


def _input_box(prompt_label: str = "你") -> str:
    """绘制矩形输入框，输入时即为完整矩形。"""
    console.print()
    console.print()
    w = console.width - 4

    top = Text()
    top.append("  ╭", style="bold cyan")
    top.append("─" * (w - 3), style="bold cyan")
    top.append("╮", style="bold cyan")
    console.print(top)

    mid = Text()
    mid.append("  │ ", style="bold cyan")
    mid.append(prompt_label, style="bold green")
    mid.append(" ❯", style="dim")
    console.print(mid, end=" ")

    console.print()

    bot = Text()
    bot.append("  ╰", style="bold cyan")
    bot.append("─" * (w - 3), style="bold cyan")
    bot.append("╯", style="bold cyan")
    console.print(bot)

    sys.stdout.write("[2A[8C")
    sys.stdout.flush()

    result = input().strip()

    return result


def _make_banner() -> Panel:
    text = Text()
    text.append(BANNER, style="bold cyan")
    text.append("\n  智能投顾助手 · AgentLoop 持久循环\n", style="dim white")
    text.append("  用自然语言提问，Agent 自主完成分析", style="dim white")
    return Panel(
        Align.center(text),
        box=box.DOUBLE,
        border_style="cyan",
        padding=(1, 2),
    )


def _make_help() -> Panel:
    content = []

    cmd_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 4))
    cmd_table.add_column("cmd", style="bold yellow", width=18)
    cmd_table.add_column("desc", style="white")
    cmd_table.add_row("/help, /h", "显示帮助")
    cmd_table.add_row("/clear, /c", "清空对话历史")
    cmd_table.add_row("/tasks", "查看后台任务")
    cmd_table.add_row("/delegate", "查看委派任务详情和日志")
    cmd_table.add_row("/exit, /quit, /q", "退出")

    title = Text("内置命令", style="bold cyan underline")
    content.append(title)
    content.append(Text())
    content.append(cmd_table)

    content.append(Text())
    content.append(Text())

    ex_title = Text("使用示例", style="bold cyan underline")
    content.append(ex_title)
    content.append(Text())

    examples = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
    examples.add_column("prompt", style="dim", width=4)
    examples.add_column("text", style="white")
    for ex in [
        "帮我分析一下平安银行",
        "今天市场整体怎么样",
        "帮我选5只强势股",
        "列出所有可用的技术因子",
        "按20日涨跌幅排名",
        "行业轮动分析",
        "回测一下 000001.SZ 和 600519.SH",
        "检查数据健康状态",
        "同步K线数据",
    ]:
        examples.add_row("▸", ex)
    content.append(examples)

    return Panel(Group(*content), title="帮助", border_style="green", padding=(1, 2))


def _make_session_info(session_id: str) -> Panel:
    text = Text()
    text.append("会话: ", style="dim")
    text.append(session_id[:8], style="bold green")
    text.append("  |  ", style="dim")
    text.append(datetime.now().strftime("%Y-%m-%d %H:%M"), style="dim")
    return Panel(text, box=box.SIMPLE, border_style="blue", padding=(0, 2))


def _run_interactive():
    """交互模式：启动 AgentLoop，持续对话。"""
    console.print(_make_banner())
    console.print()

    from alpha_agent.core.agent_loop import get_agent_loop

    agent_loop = get_agent_loop()
    session_id = str(uuid.uuid4())

    console.print(_make_session_info(session_id))

    greeting = Panel(
        "你好！我是[bold cyan]小投[/bold cyan]，你的智能投顾助手。有什么可以帮你的？\n"
        "输入 [yellow]/help[/yellow] 查看命令，直接输入问题开始分析。",
        box=box.SIMPLE,
        border_style="green",
        padding=(1, 2),
    )
    console.print(greeting)
    console.print()

    while True:
        try:
            user_input = _input_box()
        except (KeyboardInterrupt, EOFError):
            console.print()
            console.print(Panel("再见！", border_style="yellow"))
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            if user_input in ("/exit", "/quit", "/q"):
                console.print(Panel("再见！", border_style="yellow"))
                break
            if user_input in ("/help", "/h"):
                console.print(_make_help())
                continue
            if user_input in ("/clear", "/c"):
                old_session_id = session_id
                session_id = str(uuid.uuid4())
                try:
                    agent_loop._builder.cleanup_old_checkpoints(old_session_id)
                except Exception:
                    pass
                console.print(Panel(
                    f"已清空对话历史，新会话: [bold green]{session_id[:8]}[/bold green]",
                    border_style="blue",
                ))
                continue
            if user_input == "/tasks":
                _show_tasks()
                continue
            if user_input == "/delegate":
                _show_delegate_monitor()
                continue
            console.print(f"[yellow]未知命令: {user_input}，输入 /help 查看帮助[/yellow]")
            continue

        console.print()

        try:
            _stream_agent(agent_loop, session_id, user_input)
        except Exception as e:
            import traceback
            error_detail = str(e)
            if not error_detail or error_detail == "Connection error.":
                error_detail = f"{type(e).__name__}: {e}"
            logger.error(f"对话处理失败: {error_detail}\n{traceback.format_exc()}")
            console.print(Panel(f"抱歉，处理你的问题时出错了: {error_detail}", border_style="red"))
        _show_running_tasks_mini()
        console.print()
        console.print()


def _run_once(message: str):
    """单次查询模式：发送一条消息，流式输出结果后退出。"""
    from alpha_agent.core.agent_loop import get_agent_loop

    agent_loop = get_agent_loop()
    session_id = str(uuid.uuid4())

    _stream_agent(agent_loop, session_id, message)
    console.print()


def _stream_agent(agent_loop, session_id: str, user_input: str):
    """流式输出 AgentLoop 的响应。"""
    full_response = ""
    in_thinking = False
    tool_count = 0
    seen_ai_ids = set()

    with Live(console=console, refresh_per_second=10, transient=False) as live:
        status_text = Text()
        status_text.append("小投", style="bold cyan")
        status_text.append(" > ", style="dim")

        for chunk in agent_loop.stream(user_input, session_id=session_id):
            if "messages" in chunk and chunk["messages"]:
                last_msg = chunk["messages"][-1]
                if last_msg.type == "ai":
                    msg_id = getattr(last_msg, "id", None) or id(last_msg)

                    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                        if msg_id in seen_ai_ids:
                            continue
                        seen_ai_ids.add(msg_id)
                        if not in_thinking:
                            in_thinking = True
                        for tc in last_msg.tool_calls:
                            tool_count += 1
                            status_text = Text()
                            status_text.append("  ", style="dim")
                            status_text.append("🔍", style="bold blue")
                            status_text.append(" 思考中", style="italic yellow")
                            status_text.append(" · 已调用 ", style="dim")
                            status_text.append(f"{tool_count}", style="bold cyan")
                            status_text.append(" 个工具", style="dim")
                            status_text.append(f"  [🔧 {tc['name']}]", style="magenta")
                            live.update(status_text)
                    elif last_msg.content:
                        if msg_id in seen_ai_ids:
                            continue
                        seen_ai_ids.add(msg_id)
                        if in_thinking:
                            in_thinking = False
                            live.stop()
                            console.print()
                            finish = Text()
                            finish.append("  ✅ ", style="bold green")
                            finish.append(f"完成 {tool_count} 次工具调用", style="white")
                            console.print(finish)
                            console.print()
                            console.print("[bold cyan]小投[/bold cyan] [dim]>[/dim] ", end="")
                            console.print(Markdown(last_msg.content))
                            full_response = last_msg.content
                        else:
                            live.stop()
                            console.print("[bold cyan]小投[/bold cyan] [dim]>[/dim] ", end="")
                            console.print(Markdown(last_msg.content))
                            full_response = last_msg.content
                    else:
                        if msg_id in seen_ai_ids:
                            continue
                        seen_ai_ids.add(msg_id)

        if in_thinking:
            live.stop()
            console.print()
            console.print(f"  ✅ 完成 {tool_count} 次工具调用")

    if not full_response:
        state = agent_loop.graph.get_state(
            {"configurable": {"thread_id": session_id}}
        )
        messages = state.values.get("messages", [])

        for msg in reversed(messages):
            if msg.type == "ai" and msg.content and not (
                hasattr(msg, "tool_calls") and msg.tool_calls
            ):
                full_response = msg.content
                console.print("[bold cyan]小投[/bold cyan] [dim]>[/dim] ", end="")
                console.print(Markdown(msg.content))
                break

        if not full_response:
            tool_outputs = []
            for msg in reversed(messages):
                if msg.type == "tool" and msg.content:
                    tool_outputs.append(msg.content)
                if len(tool_outputs) >= 2:
                    break

            if tool_outputs:
                combined = "\n\n".join(reversed(tool_outputs))
                full_response = combined
                console.print("[bold cyan]小投[/bold cyan] [dim]>[/dim] ", end="")
                console.print(combined)


def _show_tasks():
    """显示后台任务列表。"""
    from alpha_agent.infra.process_registry import get_process_registry

    registry = get_process_registry()
    result = registry.list_tasks()

    total = result.get("total", 0)
    running = result.get("running", 0)
    tasks = result.get("tasks", [])

    if total == 0:
        console.print(Panel("当前没有后台任务", border_style="yellow"))
        return

    table = Table(
        title=f"后台任务列表（共 {total} 个，运行中 {running} 个）",
        box=box.SIMPLE_HEAVY,
        border_style="blue",
        title_style="bold cyan",
    )
    table.add_column("状态", style="bold", width=6)
    table.add_column("任务ID", style="dim", width=12)
    table.add_column("状态", width=12)
    table.add_column("耗时", width=8)
    table.add_column("命令", style="white")

    status_style = {
        "running": ("🔄", "green"),
        "completed": ("✅", "green"),
        "failed": ("❌", "red"),
        "killed": ("🛑", "red"),
        "timeout": ("⏰", "yellow"),
    }

    for t in tasks:
        tid = t.get("task_id", "")
        cmd = t.get("command", "")
        st = t.get("status", "")
        elapsed = t.get("elapsed", 0)
        emoji, color = status_style.get(st, ("⏳", "dim"))
        table.add_row(
            f"[{color}]{emoji}[/{color}]",
            tid,
            f"[{color}]{st}[/{color}]",
            f"{elapsed}s",
            cmd,
        )

    console.print(table)


def _show_running_tasks_mini():
    """在对话间隙显示运行中的后台任务（紧凑模式）。"""
    from alpha_agent.infra.process_registry import get_process_registry

    registry = get_process_registry()
    result = registry.list_tasks()

    running_tasks = [t for t in result.get("tasks", []) if t.get("status") == "running"]
    if not running_tasks:
        return

    lines = []
    for t in running_tasks:
        tid = t.get("task_id", "")[:12]
        cmd = (t.get("command", "") or "")[:50]
        elapsed = t.get("elapsed", 0)
        lines.append(
            f"  🔄 [bold yellow]{tid}[/bold yellow] "
            f"[dim]运行中 {elapsed}s[/dim]  "
            f"[white]{cmd}[/white]"
        )

    panel = Panel(
        "\n".join(lines),
        title=f"[bold yellow]后台任务 ({len(running_tasks)} 个运行中)[/bold yellow]",
        border_style="yellow",
        box=box.SIMPLE,
        padding=(0, 2),
    )
    console.print(panel)


def _show_delegate_monitor():
    """显示委派任务监控面板，包含进度、日志和干预选项。"""
    from alpha_agent.infra.process_registry import get_process_registry

    registry = get_process_registry()
    result = registry.list_tasks()
    tasks = result.get("tasks", [])
    total = result.get("total", 0)
    running = result.get("running", 0)

    delegate_tasks = [t for t in tasks if "delegate" in t.get("command", "")]
    if not delegate_tasks:
        console.print(Panel("当前没有委派任务", border_style="yellow"))
        return

    completed = [t for t in delegate_tasks if t.get("status") == "completed"]
    failed = [t for t in delegate_tasks if t.get("status") in ("failed", "timeout", "killed")]
    running_dt = [t for t in delegate_tasks if t.get("status") == "running"]

    summary = (
        f"[bold]委派任务监控[/bold]\n"
        f"总计: {len(delegate_tasks)} | "
        f"运行中: [yellow]{len(running_dt)}[/yellow] | "
        f"已完成: [green]{len(completed)}[/green] | "
        f"失败: [red]{len(failed)}[/red]"
    )
    console.print(Panel(summary, border_style="cyan", box=box.SIMPLE))

    for t in delegate_tasks:
        tid = t.get("task_id", "")
        st = t.get("status", "")
        elapsed = t.get("elapsed", 0)
        cmd = t.get("command", "")

        profile_hint = ""
        if "fundamental" in cmd:
            profile_hint = "📊 基本面分析"
        elif "technical" in cmd:
            profile_hint = "📈 技术面分析"
        elif "risk" in cmd:
            profile_hint = "🛡️ 风险控制"
        elif "data_engineer" in cmd:
            profile_hint = "🔧 数据工程"
        elif "backtest" in cmd:
            profile_hint = "🔄 回测工程"

        status_emoji = {
            "running": "🔄", "completed": "✅",
            "failed": "❌", "killed": "🛑", "timeout": "⏰",
        }.get(st, "⏳")

        console.print(f"\n  {status_emoji} [bold]{tid}[/bold] [{st}] {elapsed}s {profile_hint}")

        if st == "running":
            log_result = registry.log(tid, tail=8)
            stdout = log_result.get("stdout", "").strip()
            if stdout:
                for line in stdout.splitlines()[-5:]:
                    console.print(f"    [dim]┆ {line[:100]}[/dim]")
            else:
                console.print(f"    [dim]┆ （暂无输出）[/dim]")

            console.print(
                f"    [dim]干预: process(action='poll/log/kill', task_id='{tid}')[/dim]"
            )

        elif st == "failed":
            log_result = registry.log(tid, tail=8)
            stderr = log_result.get("stderr", "").strip()
            if stderr:
                for line in stderr.splitlines()[-3:]:
                    console.print(f"    [red]┆ ❗ {line[:100]}[/red]")

        elif st == "completed":
            log_result = registry.log(tid, tail=5)
            stdout = log_result.get("stdout", "").strip()
            result_marker = "---RESULT---"
            if result_marker in stdout:
                result_text = stdout.split(result_marker)[-1].strip()
                if result_text:
                    preview = result_text[:200]
                    console.print(f"    [green]┆ 结果: {preview}[/green]")

    stuck = registry.check_stuck_tasks()
    if stuck:
        console.print()
        console.print("[bold red]⚠️ 可能卡住的任务:[/bold red]")
        for s in stuck:
            console.print(
                f"  ⚠️ {s['task_id']} 已运行 {s['elapsed']}s - "
                f"[dim]可 kill 终止[/dim]"
            )


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