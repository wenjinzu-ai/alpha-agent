"""process 工具 —— 借鉴 Hermes 的 process 工具。

管理后台进程：poll/wait/list/kill/log。
与 terminal(background=True) 配合使用。
"""
from langchain_core.tools import tool

from alpha_agent.infra.process_registry import get_process_registry
from alpha_agent.utils.logger import logger


@tool
def process(
    action: str,
    task_id: str = "",
) -> str:
    """Manage background processes started by terminal(background=True).

    Actions:
    - poll: Check status and get new output (non-blocking). Shows progress.
    - wait: Block until process completes or timeout (default 300s).
    - list: Show all running and recently completed background processes.
    - kill: Terminate a running background process.
    - log: Get full output with pagination (last 100 lines by default).

    Usage examples:
    - process(action="poll", task_id="task_abc123")   # Check progress
    - process(action="wait", task_id="task_abc123")   # Wait for completion
    - process(action="list")                           # Show all tasks
    - process(action="kill", task_id="task_abc123")   # Terminate task
    - process(action="log", task_id="task_abc123")    # Full output log

    Args:
        action: One of: poll, wait, list, kill, log
        task_id: Task ID returned by terminal(background=True). Required for poll/wait/kill/log.
    """
    registry = get_process_registry()

    try:
        if action == "poll":
            if not task_id:
                return "错误: poll 需要提供 task_id"
            result = registry.poll(task_id)
            return _format_poll(result)

        elif action == "wait":
            if not task_id:
                return "错误: wait 需要提供 task_id"
            result = registry.wait(task_id)
            return _format_wait(result)

        elif action == "list":
            result = registry.list_tasks()
            return _format_list(result)

        elif action == "kill":
            if not task_id:
                return "错误: kill 需要提供 task_id"
            result = registry.kill(task_id)
            return _format_kill(result)

        elif action == "log":
            if not task_id:
                return "错误: log 需要提供 task_id"
            result = registry.log(task_id)
            return _format_log(result)

        else:
            return (
                f"未知操作: {action}\n"
                f"可用操作: poll, wait, list, kill, log\n\n"
                f"示例:\n"
                f"  process(action='poll', task_id='task_abc123')\n"
                f"  process(action='list')\n"
                f"  process(action='kill', task_id='task_abc123')"
            )

    except Exception as e:
        logger.error(f"[process] 操作失败: {e}")
        return f"操作失败: {e}"


def _format_poll(result: dict) -> str:
    status = result.get("status", "unknown")
    task_id = result.get("task_id", "")
    elapsed = result.get("elapsed", 0)

    if status == "not_found":
        return result.get("error", f"任务 {task_id} 不存在")

    parts = [f"任务 {task_id}"]
    parts.append(f"状态: {_status_emoji(status)} {status}")
    parts.append(f"耗时: {elapsed}s")

    new_output = result.get("new_output", "").strip()
    if new_output:
        lines = new_output.splitlines()
        if len(lines) > 20:
            parts.append(f"\n最新输出（{len(lines)}行，显示末20行）:")
            parts.append("\n".join(lines[-20:]))
        else:
            parts.append(f"\n最新输出:")
            parts.append(new_output)

    if status in ("completed", "failed", "killed", "timeout"):
        exit_code = result.get("exit_code")
        if exit_code is not None:
            parts.append(f"退出码: {exit_code}")
        full_output = result.get("full_output", "").strip()
        if full_output and not new_output:
            lines = full_output.splitlines()
            if len(lines) > 30:
                parts.append(f"\n完整输出（{len(lines)}行，显示末30行）:")
                parts.append("\n".join(lines[-30:]))
            else:
                parts.append(f"\n完整输出:")
                parts.append(full_output)
        full_error = result.get("full_error", "").strip()
        if full_error:
            parts.append(f"\n错误输出:\n{full_error[:500]}")

    return "\n".join(parts)


def _format_wait(result: dict) -> str:
    status = result.get("status", "unknown")
    task_id = result.get("task_id", "")

    if status == "not_found":
        return result.get("error", f"任务 {task_id} 不存在")

    if status == "running":
        return f"任务 {task_id} 仍在运行，等待超时。使用 process(action='poll') 查看进度。"

    return _format_poll(result)


def _format_list(result: dict) -> str:
    total = result.get("total", 0)
    running = result.get("running", 0)
    tasks = result.get("tasks", [])

    if total == 0:
        return "当前没有后台任务"

    parts = [f"后台任务列表（共{total}个，运行中{running}个）"]
    parts.append("-" * 70)

    for t in tasks:
        tid = t.get("task_id", "")
        cmd = t.get("command", "")
        st = t.get("status", "")
        elapsed = t.get("elapsed", 0)
        emoji = _status_emoji(st)
        parts.append(f"  {emoji} {tid}  [{st}]  {elapsed}s  {cmd}")

    return "\n".join(parts)


def _format_kill(result: dict) -> str:
    status = result.get("status", "unknown")
    task_id = result.get("task_id", "")

    if status == "not_found":
        return result.get("error", f"任务 {task_id} 不存在")

    if status in ("completed", "failed", "killed", "timeout"):
        return f"任务 {task_id} 已结束（状态: {status}），无需终止"

    return f"任务 {task_id} 已终止"


def _format_log(result: dict) -> str:
    task_id = result.get("task_id", "")
    status = result.get("status", "unknown")
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    total_out = result.get("total_stdout_lines", 0)
    total_err = result.get("total_stderr_lines", 0)

    parts = [f"任务 {task_id} 日志（状态: {status}）"]
    parts.append(f"输出行数: {total_out}, 错误行数: {total_err}")
    parts.append("=" * 50)

    if stdout:
        parts.append(stdout)
    if stderr:
        parts.append(f"\n--- 错误输出 ---\n{stderr}")

    if not stdout and not stderr:
        parts.append("（暂无输出）")

    return "\n".join(parts)


def _status_emoji(status: str) -> str:
    mapping = {
        "pending": "⏳",
        "running": "🔄",
        "completed": "✅",
        "failed": "❌",
        "killed": "🛑",
        "timeout": "⏰",
    }
    return mapping.get(status, "❓")