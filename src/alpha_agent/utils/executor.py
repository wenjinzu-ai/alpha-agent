"""后台脚本执行工具 —— 提供统一的临时脚本写入 + 后台执行能力。

execute_code 和 execute_pipeline 都使用此模块来避免重复的
临时文件创建、进程启动、后台消息格式化逻辑。
"""
import os
import uuid
import tempfile
from typing import Optional

from alpha_agent.infra.process_registry import get_process_registry
from alpha_agent.utils.logger import logger

_SCRIPT_DIR = os.path.join(tempfile.gettempdir(), "alpha_agent_exec")
os.makedirs(_SCRIPT_DIR, exist_ok=True)


def write_temp_script(script_code: str, prefix: str = "exec") -> str:
    """将脚本代码写入临时文件并返回路径。"""
    script_id = uuid.uuid4().hex[:12]
    path = os.path.join(_SCRIPT_DIR, f"{prefix}_{script_id}.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(script_code)
    return path


def run_script_background(
    script_path: str,
    timeout: int = 300,
    cleanup: bool = True,
) -> str:
    """后台执行 Python 脚本，返回 task_id。

    Args:
        script_path: 临时脚本路径
        timeout: 超时秒数
        cleanup: 是否在任务完成后清理临时文件

    Returns:
        task_id 字符串
    """
    registry = get_process_registry()
    cmd = f'python "{script_path}"'
    result = registry.start(command=cmd, background=True, timeout=timeout)

    task_id = result.get("task_id", "unknown")

    if cleanup:
        try:
            os.remove(script_path)
        except OSError:
            pass

    return task_id


def format_background_started(task_id: str, task_type: str, extra: Optional[str] = None) -> str:
    """格式化后台任务启动消息，与 terminal/execute_code/execute_pipeline 保持一致。"""
    lines = [
        f"后台{task_type}已启动",
        f"task_id: {task_id}",
    ]
    if extra:
        lines.append(extra)
    lines.append("")
    lines.append("使用以下命令管理任务:")
    lines.append(f"  process(action='poll', task_id='{task_id}')  # 查看进度")
    lines.append(f"  process(action='wait', task_id='{task_id}')  # 等待完成")
    lines.append(f"  process(action='log', task_id='{task_id}')   # 查看完整输出")
    lines.append(f"  process(action='kill', task_id='{task_id}')  # 终止任务")
    return "\n".join(lines)