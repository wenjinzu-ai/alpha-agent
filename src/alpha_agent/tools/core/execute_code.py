"""execute_code 工具。

在子进程中运行 Python 脚本，脚本内可调用其他工具。
多步工作流压缩为一次调用，中间结果不进上下文。

使用临时文件执行，避免 python -c 引号嵌套问题。
"""
import os
from typing import Optional
from langchain_core.tools import tool

from alpha_agent.infra.process_registry import get_process_registry
from alpha_agent.utils.executor import write_temp_script, run_script_background, format_background_started
from alpha_agent.config import settings
from alpha_agent.utils.logger import logger


_CODE_TEMPLATE = '''import sys
import json
import traceback

import pandas as pd
from datetime import datetime

from alpha_agent.infra.db.database import SessionLocal, engine
from alpha_agent.infra.db import models as db_models
from alpha_agent.utils.logger import logger

try:
    from alpha_agent.infra.sync.service import DataSyncService
    _sync_svc = DataSyncService()
except Exception:
    _sync_svc = None

try:
    from alpha_agent.infra.db.warehouse import get_data_warehouse
    _warehouse = get_data_warehouse()
except Exception:
    _warehouse = None

from sqlalchemy import text

def _execute_sql(sql: str) -> pd.DataFrame:
    with SessionLocal() as db:
        return pd.read_sql(text(sql), db.bind)

{user_code}
'''

_PROGRESS_WRAPPER = '''import sys
import json

class _ProgressTracker:
    def __init__(self, total=0):
        self.total = total
        self.current = 0

    def update(self, current, total=None, message=""):
        self.current = current
        if total is not None:
            self.total = total
        progress = (current / self.total * 100) if self.total > 0 else 0
        info = {"current": current, "total": self.total, "progress": round(progress, 1)}
        if message:
            info["message"] = message
        print(f"__PROGRESS__:{json.dumps(info)}", flush=True)

progress = _ProgressTracker()
'''


@tool
def execute_code(
    code: str,
    background: bool = False,
    timeout: int = 0,
    progress_tracking: bool = False,
) -> str:
    """Execute Python code in a subprocess. Multi-step workflows in a single call.

    Unlike terminal (which runs shell commands), this tool runs Python code
    with pre-loaded database access, data sync service, and common libraries.

    Pre-loaded variables in your code:
    - SessionLocal: SQLAlchemy session factory for database operations
    - engine: SQLAlchemy database engine
    - db_models: Database models (Stock, DailyKline, Etf, etc.)
    - pd: pandas library
    - datetime: datetime module
    - text: SQLAlchemy text() for raw SQL
    - _execute_sql(sql): Quick function to run SQL and return DataFrame
    - _sync_svc: DataSyncService instance (for data sync operations)
    - _warehouse: DataWarehouse instance

    When progress_tracking=True, a `progress` object is available:
    - progress.update(current, total, message="...")  # Report progress

    This tool compresses multi-step workflows into a single LLM call.
    Intermediate results stay in the subprocess, only final stdout enters context.

    Examples:
        # Query database
        execute_code(code="df = _execute_sql('SELECT COUNT(*) FROM stocks'); print(df)")

        # Sync data with progress
        execute_code(code="result = _sync_svc.sync_stock_list(); print(result)", background=True)

        # Complex analysis workflow
        execute_code(code=\"\"\"
        df1 = _execute_sql('SELECT * FROM daily_kline WHERE trade_date = (SELECT MAX(trade_date) FROM daily_kline)')
        stats = df1.groupby('ts_code').agg({'pct_chg': 'mean'})
        print(stats.head(20))
        \"\"\")

    Args:
        code: Python code to execute. Use print() to output results.
        background: Run in background if True. Returns task_id.
        timeout: Max seconds to wait in foreground mode. Default 300.
        progress_tracking: Enable progress tracking if True. Default False.
    """
    registry = get_process_registry()

    try:
        if timeout <= 0:
            timeout = settings.execute_code_default_timeout

        if progress_tracking:
            full_code = _PROGRESS_WRAPPER + "\n" + code
        else:
            full_code = code

        wrapped_code = _CODE_TEMPLATE.format(user_code=full_code)

        script_path = write_temp_script(wrapped_code, prefix="exec")

        result = registry.start(
            command=f'python "{script_path}"',
            background=background,
            timeout=timeout,
        )

        try:
            if not background:
                os.remove(script_path)
        except OSError:
            pass

        if background:
            task_id = result.get("task_id", "unknown")
            return format_background_started(task_id, "代码执行")

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
            filtered = _filter_progress_lines(stdout)
            if filtered:
                parts.append(f"\n=== 输出 ===\n{filtered}")

        if stderr and status != "completed":
            parts.append(f"\n=== 错误 ===\n{stderr[:500]}")

        if status == "timeout":
            parts.append(f"\n执行超时（{timeout}秒），已终止。")
            parts.append("提示: 使用 background=True 在后台运行。")

        return "\n".join(parts)

    except Exception as e:
        logger.error(f"[execute_code] 执行失败: {e}")
        return f"代码执行失败: {e}"


def _filter_progress_lines(stdout: str) -> str:
    lines = stdout.splitlines()
    filtered = [l for l in lines if not l.startswith("__PROGRESS__:")]
    return "\n".join(filtered)