from loguru import logger
import sys
import io
from pathlib import Path

from alpha_agent.config import settings

# Windows 控制台默认 GBK，遇到 emoji 会抛 UnicodeEncodeError
# 强制 stdout/stderr 使用 utf-8，避免日志和 print 输出失败
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

logger.remove()

logger.add(
    sys.stdout,
    level=settings.log_level,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    enqueue=True,
)

logger.add(
    log_dir / "alpha_agent_{time:YYYY-MM-DD}.log",
    level=settings.log_level,
    rotation="00:00",
    retention="30 days",
    compression="zip",
    enqueue=True,
    encoding="utf-8",
)

__all__ = ["logger"]
