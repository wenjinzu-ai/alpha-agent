"""错误处理与重试 - 借鉴 Hermes 的 error_classifier 和 retry_utils。

Hermes 参考:
  - agent/error_classifier.py: 错误分类 + FailoverReason
  - agent/retry_utils.py: 自适应退避 + jittered_backoff

纯 Python 实现，不依赖外部服务。
"""
import logging
import time
import random
import functools
from enum import Enum
from typing import Any, Callable, Optional, Type, Tuple

from alpha_agent.utils.logger import logger


class FailoverReason(Enum):
    """错误分类，借鉴 Hermes 的 FailoverReason。"""
    RATE_LIMIT = "rate_limit"
    CONTEXT_OVERFLOW = "context_overflow"
    OUTPUT_CAP = "output_cap"
    PROVIDER_ERROR = "provider_error"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    AUTH_ERROR = "auth_error"
    INVALID_REQUEST = "invalid_request"
    UNKNOWN = "unknown"


ERROR_PATTERNS = {
    FailoverReason.RATE_LIMIT: [
        "rate limit", "rate_limit", "too many requests",
        "429", "quota exceeded", "try again",
    ],
    FailoverReason.CONTEXT_OVERFLOW: [
        "context length", "too long", "maximum context",
        "reduce the length", "token limit", "exceeds",
    ],
    FailoverReason.OUTPUT_CAP: [
        "max_tokens", "output token", "completion too long",
    ],
    FailoverReason.AUTH_ERROR: [
        "401", "403", "unauthorized", "invalid api key",
        "authentication", "not authorized",
    ],
    FailoverReason.TIMEOUT: [
        "timeout", "timed out", "connection closed",
    ],
    FailoverReason.NETWORK_ERROR: [
        "connection", "network", "dns", "refused",
        "unreachable", "resolve",
    ],
}


def classify_error(error: Exception) -> FailoverReason:
    """分类 API 错误，返回 FailoverReason。

    借鉴 Hermes 的 classify_api_error。
    """
    error_str = str(error).lower()

    for reason, patterns in ERROR_PATTERNS.items():
        for pattern in patterns:
            if pattern in error_str:
                return reason

    error_type = type(error).__name__.lower()
    if "timeout" in error_type:
        return FailoverReason.TIMEOUT
    if "connection" in error_type:
        return FailoverReason.NETWORK_ERROR
    if "auth" in error_type or "permission" in error_type:
        return FailoverReason.AUTH_ERROR

    return FailoverReason.UNKNOWN


def jittered_backoff(base_delay: float = 1.0, max_delay: float = 60.0) -> float:
    """抖动退避，借鉴 Hermes 的 jittered_backoff。

    返回带随机抖动的退避时间。
    """
    jitter = random.uniform(0, base_delay * 0.5)
    return min(base_delay + jitter, max_delay)


def adaptive_rate_limit_backoff(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 120.0,
) -> float:
    """自适应速率限制退避，借鉴 Hermes 的 adaptive_rate_limit_backoff。

    指数退避 + 随机抖动。
    """
    delay = base_delay * (2 ** min(attempt, 8))
    jitter = random.uniform(0, delay * 0.3)
    return min(delay + jitter, max_delay)


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable: Tuple[FailoverReason, ...] = (
        FailoverReason.RATE_LIMIT,
        FailoverReason.NETWORK_ERROR,
        FailoverReason.TIMEOUT,
        FailoverReason.PROVIDER_ERROR,
    ),
):
    """重试装饰器，借鉴 Hermes 的错误处理策略。

    Args:
        max_attempts: 最大重试次数
        base_delay: 基础退避时间
        max_delay: 最大退避时间
        retryable: 可重试的错误类型
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_error = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    reason = classify_error(e)

                    if reason not in retryable:
                        logger.error(
                            f"[Retry] 不可重试错误 ({reason.value}): {e}"
                        )
                        raise

                    if attempt < max_attempts - 1:
                        if reason == FailoverReason.RATE_LIMIT:
                            delay = adaptive_rate_limit_backoff(attempt, base_delay, max_delay)
                        else:
                            delay = jittered_backoff(base_delay * (attempt + 1), max_delay)

                        logger.warning(
                            f"[Retry] {func.__name__} 失败 "
                            f"({reason.value}, 第 {attempt + 1}/{max_attempts} 次), "
                            f"{delay:.1f}s 后重试"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"[Retry] {func.__name__} 重试 {max_attempts} 次全部失败"
                        )
                        raise

            raise last_error

        return wrapper
    return decorator