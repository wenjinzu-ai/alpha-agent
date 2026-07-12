"""线程级中断信号 —— 借鉴 Hermes 的 interrupt.py。

支持多会话并发中断，每个线程独立管理中断状态。
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_interrupted_threads: set[int] = set()
_lock = threading.Lock()


def set_interrupt(active: bool, thread_id: int | None = None) -> None:
    tid = thread_id if thread_id is not None else threading.current_thread().ident
    with _lock:
        if active:
            _interrupted_threads.add(tid)
        else:
            _interrupted_threads.discard(tid)


def is_interrupted() -> bool:
    tid = threading.current_thread().ident
    with _lock:
        return tid in _interrupted_threads


def clear_current_thread_interrupt() -> None:
    set_interrupt(False)


class ThreadAwareEventProxy:
    def is_set(self) -> bool:
        return is_interrupted()

    def set(self) -> None:
        set_interrupt(True)

    def clear(self) -> None:
        set_interrupt(False)


_interrupt_event = ThreadAwareEventProxy()
