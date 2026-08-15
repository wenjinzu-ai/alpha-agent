"""process 工具。

管理后台进程和委派子Agent：poll/wait/list/kill/log/monitor。

支持两类任务：
1. ProcessRegistry: terminal(background=True) 创建的后台进程
2. DelegateRegistry: delegate_task 创建的线程池子Agent

统一完成队列设计：
  - 子Agent完成后结果自动注入对话上下文
  - 主Agent可随时查看子Agent日志和进度
  - 主Agent可终止卡住的子Agent
"""
from langchain_core.tools import tool

from alpha_agent.infra.process_registry import get_process_registry
from alpha_agent.utils.logger import logger


@tool
def process(
    action: str,
    task_id: str = "",
) -> str:
    """Manage background processes and delegated sub-agents.

    Actions:
    - poll: Check status and get new output (non-blocking). Works for both processes and sub-agents.
    - wait: Block until process/sub-agent completes or timeout (default 300s).
    - list: Show all running and recently completed background processes and sub-agents.
    - kill: Terminate a running background process or sub-agent.
    - log: Get output log for processes, or execution log for sub-agents.
    - monitor: Check all delegated tasks for progress, detect stuck tasks, show summary.

    Usage examples:
    - process(action="poll", task_id="deleg_abc123")   # Check sub-agent progress
    - process(action="poll", task_id="task_abc123")    # Check process progress
    - process(action="wait", task_id="deleg_abc123")   # Wait for sub-agent
    - process(action="list")                            # Show all tasks
    - process(action="kill", task_id="deleg_abc123")   # Terminate sub-agent
    - process(action="log", task_id="deleg_abc123")    # View sub-agent execution log
    - process(action="monitor")                         # Monitor all delegated tasks

    Args:
        action: One of: poll, wait, list, kill, log, monitor
        task_id: Task ID (deleg_xxx for sub-agents, task_xxx for processes). Required for poll/wait/kill/log.
    """
    try:
        if task_id and task_id.startswith("deleg_"):
            return _handle_delegate_action(action, task_id)

        registry = get_process_registry()

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
            return _format_combined_list(registry)

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

        elif action == "monitor":
            return _format_monitor(registry)

        else:
            return (
                f"未知操作: {action}\n"
                f"可用操作: poll, wait, list, kill, log, monitor\n\n"
                f"示例:\n"
                f"  process(action='poll', task_id='deleg_abc123')\n"
                f"  process(action='list')\n"
                f"  process(action='kill', task_id='deleg_abc123')\n"
                f"  process(action='monitor')  # 监控所有委派任务"
            )

    except Exception as e:
        logger.error(f"[process] 操作失败: {e}")
        return f"操作失败: {e}"


def _handle_delegate_action(action: str, delegation_id: str) -> str:
    from alpha_agent.tools.core.delegate import DelegateRegistry

    delegate_reg = DelegateRegistry.get()
    record = delegate_reg.get_record(delegation_id)

    if not record:
        return f"委派任务 {delegation_id} 不存在"

    if action == "poll":
        progress = record.get_progress()
        parts = [
            f"委派子Agent {delegation_id}",
            f"状态: {_status_emoji(progress['status'])} {progress['status']}",
            f"目标: {progress['goal']}",
            f"Profile: {progress['profile']}",
            f"耗时: {progress['elapsed']}s",
            f"步数: {progress['step_count']}, 工具调用: {progress['tool_count']}",
            f"日志行数: {progress['log_lines']}",
        ]

        if progress["status"] == "completed":
            parts.append(f"\n✅ 执行结果:")
            result = record.result or "(无结果)"
            if len(result) > 2000:
                parts.append(result[:2000] + "\n... (结果过长，已截断)")
            else:
                parts.append(result)
        elif progress["status"] == "failed":
            parts.append(f"\n❌ 失败原因: {progress['error']}")
        elif progress["status"] == "running":
            tail = record.get_log_tail(5)
            if tail:
                parts.append(f"\n最近日志:")
                for line in tail:
                    parts.append(f"  ┆ {line[:100]}")

        return "\n".join(parts)

    elif action == "wait":
        import time
        timeout = 300
        start = time.time()
        while time.time() - start < timeout:
            if record.status != "running":
                break
            time.sleep(2)

        if record.status == "running":
            return f"委派子Agent {delegation_id} 仍在运行，等待超时。使用 process(action='poll') 查看进度。"

        return _handle_delegate_action("poll", delegation_id)

    elif action == "kill":
        if record.status != "running":
            return f"委派子Agent {delegation_id} 已结束（状态: {record.status}），无需终止"

        success = delegate_reg.kill(delegation_id)
        if success:
            return f"委派子Agent {delegation_id} 已发送终止信号"
        return f"委派子Agent {delegation_id} 终止失败"

    elif action == "log":
        progress = record.get_progress()
        parts = [
            f"委派子Agent {delegation_id} 执行日志（状态: {progress['status']}）",
            f"目标: {progress['goal']}",
            f"Profile: {progress['profile']}",
            f"耗时: {progress['elapsed']}s | 步数: {progress['step_count']} | 工具调用: {progress['tool_count']}",
            "=" * 60,
        ]

        all_logs = record.get_log_tail(100)
        if all_logs:
            parts.extend(all_logs)
        else:
            parts.append("（暂无日志）")

        if record.result:
            parts.append("=" * 60)
            parts.append("执行结果:")
            result = record.result
            if len(result) > 3000:
                parts.append(result[:3000] + "\n... (结果过长，已截断)")
            else:
                parts.append(result)

        return "\n".join(parts)

    else:
        return f"不支持的操作: {action}。可用: poll, wait, kill, log"


def _format_poll(result: dict) -> str:
    status = result.get("status", "unknown")
    task_id = result.get("task_id", "")

    if status == "not_found":
        return result.get("error", f"任务 {task_id} 不存在")

    parts = [f"任务 {task_id}"]
    parts.append(f"状态: {_status_emoji(status)} {status}")
    parts.append(f"耗时: {result.get('elapsed', 0)}s")

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


def _format_combined_list(registry) -> str:
    from alpha_agent.tools.core.delegate import DelegateRegistry

    proc_result = registry.list_tasks()
    delegate_reg = DelegateRegistry.get()
    delegate_records = delegate_reg.list_records()

    proc_total = proc_result.get("total", 0)
    proc_running = proc_result.get("running", 0)
    delegate_total = len(delegate_records)
    delegate_running = sum(1 for r in delegate_records if r.status == "running")

    if proc_total == 0 and delegate_total == 0:
        return "当前没有后台任务"

    parts = [
        f"后台任务列表",
        f"进程: {proc_total}个（运行中{proc_running}个）| 子Agent: {delegate_total}个（运行中{delegate_running}个）",
        "-" * 70,
    ]

    for t in proc_result.get("tasks", []):
        tid = t.get("task_id", "")
        cmd = t.get("command", "")
        st = t.get("status", "")
        elapsed = t.get("elapsed", 0)
        emoji = _status_emoji(st)
        parts.append(f"  {emoji} {tid}  [{st}]  {elapsed}s  {cmd[:60]}")

    for r in delegate_records:
        progress = r.get_progress()
        emoji = _status_emoji(progress["status"])
        parts.append(
            f"  {emoji} {r.delegation_id}  [{progress['status']}]  "
            f"{progress['elapsed']}s  [{progress['profile']}] {progress['goal']}"
        )

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
        "possibly_stuck": "⚠️",
    }
    return mapping.get(status, "❓")


def _format_monitor(registry) -> str:
    from alpha_agent.tools.core.delegate import DelegateRegistry

    delegate_reg = DelegateRegistry.get()
    delegate_records = delegate_reg.list_records()
    proc_result = registry.list_tasks()

    proc_tasks = proc_result.get("tasks", [])
    delegate_running = [r for r in delegate_records if r.status == "running"]
    delegate_completed = [r for r in delegate_records if r.status == "completed"]
    delegate_failed = [r for r in delegate_records if r.status == "failed"]

    if not proc_tasks and not delegate_records:
        return "当前没有后台任务"

    parts = [
        f"📊 任务监控面板",
        f"{'='*50}",
        f"子Agent: {len(delegate_records)}个（运行中{len(delegate_running)}个 | "
        f"已完成{len(delegate_completed)}个 | 失败{len(delegate_failed)}个）",
        f"后台进程: {proc_result.get('total', 0)}个（运行中{proc_result.get('running', 0)}个）",
        f"{'='*50}",
    ]

    if delegate_running:
        parts.append(f"\n🔄 运行中的子Agent:")
        for r in delegate_running:
            progress = r.get_progress()
            parts.append(
                f"  🔄 {r.delegation_id} [{progress['profile']}] "
                f"已运行{progress['elapsed']}s | 步数:{progress['step_count']} 工具:{progress['tool_count']}"
            )
            tail = r.get_log_tail(3)
            for line in tail:
                parts.append(f"    ┆ {line[:100]}")

    if delegate_completed:
        parts.append(f"\n✅ 已完成的子Agent:")
        for r in delegate_completed:
            progress = r.get_progress()
            result_preview = (r.result or "")[:80].replace("\n", " ")
            parts.append(
                f"  ✅ {r.delegation_id} [{progress['profile']}] "
                f"耗时{progress['elapsed']}s | {result_preview}"
            )

    if delegate_failed:
        parts.append(f"\n❌ 失败的子Agent:")
        for r in delegate_failed:
            parts.append(
                f"  ❌ {r.delegation_id} [{r.profile}] 错误: {r.error}"
            )

    stuck = registry.check_stuck_tasks()
    if stuck:
        parts.append(f"\n⚠️ 可能卡住的后台进程 ({len(stuck)} 个):")
        for s in stuck:
            parts.append(f"  ⚠️ {s['task_id']} 已运行 {s['elapsed']}s")

    if delegate_running:
        parts.append(f"\n💡 干预命令:")
        for r in delegate_running:
            parts.append(f"  process(action='poll', task_id='{r.delegation_id}')  # 查看进度")
            parts.append(f"  process(action='log', task_id='{r.delegation_id}')   # 查看日志")
            parts.append(f"  process(action='kill', task_id='{r.delegation_id}')  # 终止")

    return "\n".join(parts)