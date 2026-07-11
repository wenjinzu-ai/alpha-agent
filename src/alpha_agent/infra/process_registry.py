"""后台进程注册表 —— 管理子进程的完整生命周期。

借鉴 Hermes 的 ProcessRegistry：
- 支持前台/后台执行
- 后台进程可 poll/wait/kill/log
- 超时自动终止（SIGTERM → 5s → SIGKILL）
- 线程安全
"""
import subprocess
import threading
import uuid
import time
import os
import signal
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum

from alpha_agent.utils.logger import logger


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"
    TIMEOUT = "timeout"


@dataclass
class TaskInfo:
    task_id: str
    command: str
    status: TaskStatus = TaskStatus.PENDING
    process: Optional[subprocess.Popen] = None
    workdir: Optional[str] = None
    timeout: int = 180
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    exit_code: Optional[int] = None
    stdout_lines: List[str] = field(default_factory=list)
    stderr_lines: List[str] = field(default_factory=list)
    _stdout_pos: int = 0
    _stderr_pos: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at or time.time()
        return round(end - self.started_at, 1)

    @property
    def new_stdout(self) -> str:
        with self._lock:
            new = "".join(self.stdout_lines[self._stdout_pos:])
            self._stdout_pos = len(self.stdout_lines)
            return new

    @property
    def new_stderr(self) -> str:
        with self._lock:
            new = "".join(self.stderr_lines[self._stderr_pos:])
            self._stderr_pos = len(self.stderr_lines)
            return new

    @property
    def full_stdout(self) -> str:
        with self._lock:
            return "".join(self.stdout_lines)

    @property
    def full_stderr(self) -> str:
        with self._lock:
            return "".join(self.stderr_lines)

    def append_stdout(self, data: str):
        with self._lock:
            self.stdout_lines.append(data)

    def append_stderr(self, data: str):
        with self._lock:
            self.stderr_lines.append(data)


class ProcessRegistry:
    def __init__(self):
        self._tasks: Dict[str, TaskInfo] = {}
        self._lock = threading.Lock()
        self._watchers: Dict[str, threading.Thread] = {}

    def _generate_task_id(self) -> str:
        return f"task_{uuid.uuid4().hex[:8]}"

    def start(
        self,
        command: str,
        background: bool = False,
        timeout: int = 180,
        workdir: Optional[str] = None,
    ) -> Dict[str, Any]:
        task_id = self._generate_task_id()
        task = TaskInfo(
            task_id=task_id,
            command=command,
            status=TaskStatus.PENDING,
            timeout=timeout,
            workdir=workdir,
        )

        with self._lock:
            self._tasks[task_id] = task

        try:
            is_windows = os.name == "nt"
            cwd = workdir or os.getcwd()

            if is_windows:
                popen_kwargs = {
                    "args": command,
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE,
                    "shell": True,
                    "cwd": cwd,
                    "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
                }
            else:
                popen_kwargs = {
                    "args": ["bash", "-c", command],
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE,
                    "cwd": cwd,
                    "start_new_session": True,
                }

            proc = subprocess.Popen(**popen_kwargs)
            task.process = proc
            task.status = TaskStatus.RUNNING
            task.started_at = time.time()

            logger.info(f"[ProcessRegistry] 启动任务 {task_id}: {command[:80]}")

            if background:
                watcher = threading.Thread(
                    target=self._watch_process,
                    args=(task_id,),
                    daemon=True,
                    name=f"watcher-{task_id}",
                )
                with self._lock:
                    self._watchers[task_id] = watcher
                watcher.start()

                return {
                    "task_id": task_id,
                    "status": "running",
                    "command": command,
                    "message": f"后台任务已启动，使用 process(action='poll', task_id='{task_id}') 查看进度",
                }
            else:
                return self._wait_foreground(task_id, timeout)

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.finished_at = time.time()
            logger.error(f"[ProcessRegistry] 启动任务失败 {task_id}: {e}")
            return {
                "task_id": task_id,
                "status": "failed",
                "error": str(e),
            }

    def _wait_foreground(self, task_id: str, timeout: int) -> Dict[str, Any]:
        task = self._tasks.get(task_id)
        if not task or not task.process:
            return {"task_id": task_id, "status": "failed", "error": "进程不存在"}

        proc = task.process
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            task.finished_at = time.time()

            if stdout:
                task.append_stdout(stdout.decode("utf-8", errors="replace"))
            if stderr:
                task.append_stderr(stderr.decode("utf-8", errors="replace"))

            task.exit_code = proc.returncode

            if proc.returncode == 0:
                task.status = TaskStatus.COMPLETED
            else:
                task.status = TaskStatus.FAILED

            result = {
                "task_id": task_id,
                "status": task.status.value,
                "exit_code": proc.returncode,
                "elapsed": task.elapsed,
            }

            stdout_str = task.full_stdout.strip()
            stderr_str = task.full_stderr.strip()

            if stdout_str:
                result["stdout"] = stdout_str
            if stderr_str:
                result["stderr"] = stderr_str

            return result

        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            task.status = TaskStatus.TIMEOUT
            task.exit_code = -9
            task.finished_at = time.time()
            logger.warning(f"[ProcessRegistry] 任务超时 {task_id} ({timeout}s)")
            return {
                "task_id": task_id,
                "status": "timeout",
                "error": f"命令执行超时（{timeout}秒），已终止",
                "elapsed": task.elapsed,
            }

    def _watch_process(self, task_id: str):
        task = self._tasks.get(task_id)
        if not task or not task.process:
            return

        proc = task.process
        timeout_at = task.started_at + task.timeout if task.started_at else time.time() + task.timeout

        try:
            while proc.poll() is None:
                if time.time() > timeout_at:
                    self._kill_process(task_id, reason="timeout")
                    return

                try:
                    if proc.stdout:
                        line = proc.stdout.readline()
                        if line:
                            task.append_stdout(line.decode("utf-8", errors="replace"))
                    if proc.stderr:
                        line = proc.stderr.readline()
                        if line:
                            task.append_stderr(line.decode("utf-8", errors="replace"))
                except Exception:
                    pass

                time.sleep(0.05)

            remaining_stdout, remaining_stderr = proc.communicate(timeout=5)
            if remaining_stdout:
                task.append_stdout(remaining_stdout.decode("utf-8", errors="replace"))
            if remaining_stderr:
                task.append_stderr(remaining_stderr.decode("utf-8", errors="replace"))

            task.exit_code = proc.returncode
            task.finished_at = time.time()

            if task.status == TaskStatus.KILLED:
                pass
            elif proc.returncode == 0:
                task.status = TaskStatus.COMPLETED
                logger.info(f"[ProcessRegistry] 后台任务完成 {task_id} (耗时 {task.elapsed}s)")
            else:
                task.status = TaskStatus.FAILED
                logger.warning(f"[ProcessRegistry] 后台任务失败 {task_id} (exit={proc.returncode})")

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.finished_at = time.time()
            logger.error(f"[ProcessRegistry] 监控线程异常 {task_id}: {e}")

    def _kill_process(self, task_id: str, reason: str = "manual"):
        task = self._tasks.get(task_id)
        if not task or not task.process:
            return

        proc = task.process
        is_windows = os.name == "nt"

        try:
            if is_windows:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
            else:
                proc.send_signal(signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.send_signal(signal.SIGKILL)
                    proc.wait(timeout=3)

            task.exit_code = proc.returncode
            task.finished_at = time.time()

            if reason == "timeout":
                task.status = TaskStatus.TIMEOUT
            else:
                task.status = TaskStatus.KILLED

            logger.info(f"[ProcessRegistry] 终止任务 {task_id} (原因: {reason})")

        except Exception as e:
            logger.error(f"[ProcessRegistry] 终止任务失败 {task_id}: {e}")

    def poll(self, task_id: str) -> Dict[str, Any]:
        task = self._tasks.get(task_id)
        if not task:
            return {"task_id": task_id, "status": "not_found", "error": f"任务 {task_id} 不存在"}

        result = {
            "task_id": task_id,
            "status": task.status.value,
            "elapsed": task.elapsed,
        }

        new_out = task.new_stdout
        new_err = task.new_stderr
        if new_out:
            result["new_output"] = new_out
        if new_err:
            result["new_error"] = new_err
        if task.exit_code is not None:
            result["exit_code"] = task.exit_code

        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.KILLED, TaskStatus.TIMEOUT):
            result["full_output"] = task.full_stdout
            stderr = task.full_stderr.strip()
            if stderr:
                result["full_error"] = stderr

        return result

    def wait(self, task_id: str, timeout: int = 300) -> Dict[str, Any]:
        task = self._tasks.get(task_id)
        if not task:
            return {"task_id": task_id, "status": "not_found", "error": f"任务 {task_id} 不存在"}

        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.KILLED, TaskStatus.TIMEOUT):
            return self.poll(task_id)

        if task.process:
            try:
                task.process.wait(timeout=timeout)
                time.sleep(0.2)
            except subprocess.TimeoutExpired:
                return {
                    "task_id": task_id,
                    "status": "running",
                    "message": f"任务仍在运行，等待超时（{timeout}秒）",
                    "elapsed": task.elapsed,
                }

        return self.poll(task_id)

    def kill(self, task_id: str) -> Dict[str, Any]:
        task = self._tasks.get(task_id)
        if not task:
            return {"task_id": task_id, "status": "not_found", "error": f"任务 {task_id} 不存在"}

        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.KILLED, TaskStatus.TIMEOUT):
            return {"task_id": task_id, "status": task.status.value, "message": "任务已结束"}

        self._kill_process(task_id, reason="manual")
        return self.poll(task_id)

    def list_tasks(self) -> Dict[str, Any]:
        tasks = []
        with self._lock:
            for task_id, task in self._tasks.items():
                tasks.append({
                    "task_id": task_id,
                    "command": task.command[:80],
                    "status": task.status.value,
                    "elapsed": task.elapsed,
                    "exit_code": task.exit_code,
                })

        running = [t for t in tasks if t["status"] == "running"]
        completed = [t for t in tasks if t["status"] not in ("running", "pending")]

        return {
            "total": len(tasks),
            "running": len(running),
            "completed": len(completed),
            "tasks": sorted(tasks, key=lambda t: t.get("elapsed", 0), reverse=True),
        }

    def log(self, task_id: str, tail: int = 100) -> Dict[str, Any]:
        task = self._tasks.get(task_id)
        if not task:
            return {"task_id": task_id, "status": "not_found", "error": f"任务 {task_id} 不存在"}

        stdout = task.full_stdout
        stderr = task.full_stderr

        if tail > 0:
            stdout_lines = stdout.splitlines()
            stdout = "\n".join(stdout_lines[-tail:])
            stderr_lines = stderr.splitlines()
            stderr = "\n".join(stderr_lines[-tail:])

        return {
            "task_id": task_id,
            "status": task.status.value,
            "stdout": stdout,
            "stderr": stderr,
            "total_stdout_lines": len(task.full_stdout.splitlines()),
            "total_stderr_lines": len(task.full_stderr.splitlines()),
        }

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        return self._tasks.get(task_id)


_registry: Optional[ProcessRegistry] = None


def get_process_registry() -> ProcessRegistry:
    global _registry
    if _registry is None:
        _registry = ProcessRegistry()
        logger.info("[ProcessRegistry] 初始化完成")
    return _registry