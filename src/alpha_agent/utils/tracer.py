"""
内置追踪器（免费替代 LangSmith/LangFuse）

追踪 LLM 调用、工具调用、Worker 执行，便于调试和性能分析。
数据存储在本地目录中，可通过 API 查询。
"""
import json
import os
import time
import threading
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from pathlib import Path

from alpha_agent.utils.logger import logger


TZ_UTC8 = timezone(timedelta(hours=8))


class Tracer:
    """内置追踪器 —— 免费的 LLM 调用可观测性方案"""

    def __init__(self, storage_dir: str = None):
        if storage_dir is None:
            storage_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "data", "traces"
            )
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._buffer: List[Dict[str, Any]] = []
        self._max_buffer = 100

    def _now(self) -> str:
        return datetime.now(TZ_UTC8).isoformat()

    def _save(self, trace: Dict[str, Any]):
        with self._lock:
            self._buffer.append(trace)
            if len(self._buffer) >= self._max_buffer:
                self._flush()

    def _flush(self):
        if not self._buffer:
            return
        date_str = datetime.now(TZ_UTC8).strftime("%Y-%m-%d")
        file_path = self._storage_dir / f"trace_{date_str}.jsonl"
        try:
            with open(file_path, "a", encoding="utf-8") as f:
                for t in self._buffer:
                    f.write(json.dumps(t, ensure_ascii=False) + "\n")
            self._buffer.clear()
        except Exception as e:
            logger.error(f"[Tracer] 写入失败: {e}")

    def trace_llm_call(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: float = 0,
        session_id: str = "",
        worker_name: str = "",
        success: bool = True,
        error: str = "",
    ):
        self._save({
            "type": "llm_call",
            "timestamp": self._now(),
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "latency_ms": round(latency_ms, 2),
            "session_id": session_id,
            "worker_name": worker_name,
            "success": success,
            "error": error,
        })

    def trace_tool_call(
        self,
        tool_name: str,
        args: Dict[str, Any] = None,
        latency_ms: float = 0,
        session_id: str = "",
        worker_name: str = "",
        success: bool = True,
        error: str = "",
    ):
        self._save({
            "type": "tool_call",
            "timestamp": self._now(),
            "tool_name": tool_name,
            "args": args or {},
            "latency_ms": round(latency_ms, 2),
            "session_id": session_id,
            "worker_name": worker_name,
            "success": success,
            "error": error,
        })

    def trace_worker_execution(
        self,
        worker_name: str,
        worker_display_name: str,
        steps: int = 0,
        tool_calls: int = 0,
        latency_ms: float = 0,
        session_id: str = "",
        status: str = "completed",
        error: str = "",
    ):
        self._save({
            "type": "worker_execution",
            "timestamp": self._now(),
            "worker_name": worker_name,
            "worker_display_name": worker_display_name,
            "steps": steps,
            "tool_calls": tool_calls,
            "latency_ms": round(latency_ms, 2),
            "session_id": session_id,
            "status": status,
            "error": error,
        })

    def trace_session(
        self,
        session_id: str,
        user_message: str,
        selected_workers: List[str] = None,
        total_latency_ms: float = 0,
        status: str = "completed",
    ):
        self._save({
            "type": "session",
            "timestamp": self._now(),
            "session_id": session_id,
            "user_message": user_message[:200],
            "selected_workers": selected_workers or [],
            "total_latency_ms": round(total_latency_ms, 2),
            "status": status,
        })

    def get_stats(self, days: int = 7) -> Dict[str, Any]:
        """获取统计信息"""
        self._flush()
        cutoff = datetime.now(TZ_UTC8) - timedelta(days=days)
        traces = self._load_traces(cutoff)

        stats = {
            "period_days": days,
            "total_llm_calls": 0,
            "total_tool_calls": 0,
            "total_worker_executions": 0,
            "total_sessions": 0,
            "total_tokens": 0,
            "avg_llm_latency_ms": 0.0,
            "avg_tool_latency_ms": 0.0,
            "worker_stats": {},
            "tool_stats": {},
            "success_rate": 0.0,
        }

        llm_latencies = []
        tool_latencies = []
        total = 0
        succeeded = 0

        for t in traces:
            total += 1
            if t.get("success", True):
                succeeded += 1

            if t["type"] == "llm_call":
                stats["total_llm_calls"] += 1
                stats["total_tokens"] += t.get("total_tokens", 0)
                if t.get("latency_ms"):
                    llm_latencies.append(t["latency_ms"])

            elif t["type"] == "tool_call":
                stats["total_tool_calls"] += 1
                tool_name = t.get("tool_name", "unknown")
                if tool_name not in stats["tool_stats"]:
                    stats["tool_stats"][tool_name] = 0
                stats["tool_stats"][tool_name] += 1
                if t.get("latency_ms"):
                    tool_latencies.append(t["latency_ms"])

            elif t["type"] == "worker_execution":
                stats["total_worker_executions"] += 1
                wn = t.get("worker_display_name", t.get("worker_name", "unknown"))
                if wn not in stats["worker_stats"]:
                    stats["worker_stats"][wn] = {"count": 0, "total_steps": 0, "errors": 0}
                stats["worker_stats"][wn]["count"] += 1
                stats["worker_stats"][wn]["total_steps"] += t.get("steps", 0)
                if t.get("status") == "failed":
                    stats["worker_stats"][wn]["errors"] += 1

            elif t["type"] == "session":
                stats["total_sessions"] += 1

        if llm_latencies:
            stats["avg_llm_latency_ms"] = round(sum(llm_latencies) / len(llm_latencies), 2)
        if tool_latencies:
            stats["avg_tool_latency_ms"] = round(sum(tool_latencies) / len(tool_latencies), 2)
        if total > 0:
            stats["success_rate"] = round(succeeded / total * 100, 2)

        return stats

    def _load_traces(self, cutoff: datetime) -> List[Dict[str, Any]]:
        traces = []
        for file_path in sorted(self._storage_dir.glob("trace_*.jsonl")):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            t = json.loads(line)
                            ts = t.get("timestamp", "")
                            if ts >= cutoff.isoformat():
                                traces.append(t)
                        except json.JSONDecodeError:
                            continue
            except Exception:
                continue
        return traces

    def get_recent_traces(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近的追踪记录"""
        self._flush()
        traces = []
        for file_path in sorted(self._storage_dir.glob("trace_*.jsonl"), reverse=True):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    for line in reversed(lines):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            traces.append(json.loads(line))
                            if len(traces) >= limit:
                                return traces
                        except json.JSONDecodeError:
                            continue
            except Exception:
                continue
        return traces

    def clear_old_traces(self, days: int = 30):
        """清理旧追踪数据"""
        cutoff = datetime.now(TZ_UTC8) - timedelta(days=days)
        for file_path in self._storage_dir.glob("trace_*.jsonl"):
            try:
                file_date = file_path.stem.replace("trace_", "")
                if file_date < cutoff.strftime("%Y-%m-%d"):
                    file_path.unlink()
                    logger.info(f"[Tracer] 清理过期文件: {file_path.name}")
            except Exception:
                continue


_tracer: Optional[Tracer] = None


def get_tracer() -> Tracer:
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer