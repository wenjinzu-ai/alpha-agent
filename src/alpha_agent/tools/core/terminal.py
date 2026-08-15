"""terminal 工具。

支持前台/后台执行任意 Shell 命令。
前台模式：阻塞直到命令完成，返回输出。
后台模式：立即返回 task_id，使用 process 工具查看进度。
"""
from typing import Optional
from langchain_core.tools import tool

from alpha_agent.infra.process_registry import get_process_registry
from alpha_agent.utils.executor import format_background_started
from alpha_agent.config import settings
from alpha_agent.utils.logger import logger


@tool
def terminal(
    command: str,
    background: bool = False,
    timeout: int = 0,
    workdir: Optional[str] = None,
) -> str:
    """Execute shell commands. Supports foreground and background modes.

    Foreground mode (background=False): Blocks until command completes.
    Returns output, exit code, and error if any.

    Background mode (background=True): Returns immediately with task_id.
    Use process(action="poll", task_id=...) to check progress,
    process(action="wait", task_id=...) to block until done,
    process(action="log", task_id=...) to see full output,
    process(action="kill", task_id=...) to terminate.

    This is the most versatile tool - you can execute any command:
    - Python scripts: terminal("python scripts/sync_stock_kline.py", background=True)
    - Database operations: terminal("python -c \\"from alpha_agent.infra.db.database import SessionLocal; ...\\"")
    - Package management: terminal("pip install akshare --upgrade")
    - File operations: terminal("dir scripts\\")

    For complex multi-step Python workflows, prefer execute_code instead.

    Args:
        command: Shell command to execute
        background: Run in background (non-blocking) if True. Default False.
        timeout: Max seconds to wait in foreground mode. Default 180.
        workdir: Working directory. Default: project root.
    """
    registry = get_process_registry()

    try:
        if timeout <= 0:
            timeout = settings.terminal_default_timeout

        result = registry.start(
            command=command,
            background=background,
            timeout=timeout,
            workdir=workdir,
        )

        if background:
            task_id = result.get("task_id", "unknown")
            return format_background_started(task_id, "任务", f"命令: {command[:80]}")

        status = result.get("status", "unknown")
        exit_code = result.get("exit_code")
        elapsed = result.get("elapsed", 0)

        parts = [f"状态: {status}"]
        if exit_code is not None:
            parts.append(f"退出码: {exit_code}")
        parts.append(f"耗时: {elapsed}s")

        stdout = result.get("stdout", "").strip()
        stderr = result.get("stderr", "").strip()

        if stdout:
            parts.append(f"\n=== 输出 ===\n{stdout}")
        if stderr:
            parts.append(f"\n=== 错误 ===\n{stderr}")

        if status == "timeout":
            parts.append(f"\n命令执行超时（{timeout}秒），已自动终止。")
            parts.append("提示: 使用 background=True 在后台运行长时间任务。")

        return "\n".join(parts)

    except Exception as e:
        logger.error(f"[terminal] 执行失败: {e}")
        return f"命令执行失败: {e}"