"""Pipeline 数据库工具 —— 统一的 DB 会话管理和错误处理。

所有 Pipeline 步骤函数中重复的 from alpha_agent.infra.db.database import
SessionLocal / from sqlalchemy import text 模式，提取到此模块统一管理。
"""
from contextlib import contextmanager
from typing import Optional, Any, Dict, List

from alpha_agent.infra.db.database import SessionLocal
from alpha_agent.utils.logger import logger


@contextmanager
def pipeline_db():
    """Pipeline 专用数据库上下文管理器。

    统一处理 Session 创建/关闭和异常捕获。
    """
    try:
        with SessionLocal() as db:
            yield db
    except Exception as e:
        logger.error(f"[Pipeline] DB error: {e}")
        raise


def execute_sql(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Any]:
    """执行 SQL 查询并返回所有行。

    Args:
        sql: SQL 查询语句（使用 :param 命名参数）
        params: 参数字典

    Returns:
        查询结果列表
    """
    from sqlalchemy import text

    with pipeline_db() as db:
        result = db.execute(text(sql), params or {})
        return result.fetchall()