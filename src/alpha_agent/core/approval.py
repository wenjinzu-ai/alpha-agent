"""危险操作审批系统。

多层递进检测：
  1. Hardline 检测（无条件阻断）
  2. Sudo stdin 守卫
  3. 用户自定义拒绝规则
  4. 审批模式旁路（off 模式跳过）
  5. 永久白名单
  6. 危险模式检测 → 触发审批流程
  7. 审批决策：manual / smart / off

审批模式：
  - manual: 所有危险操作暂停等待用户审批
  - smart: 辅助 LLM 评估风险，低风险自动通过
  - off: 跳过所有审批（仅开发/测试环境）
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ApprovalMode(str, Enum):
    MANUAL = "manual"
    SMART = "smart"
    OFF = "off"


# ============================================================================
# Hardline 模式 —— 无条件阻断
# ============================================================================

HARDLINE_PATTERNS: list[tuple[str, str]] = [
    (r'\brm\s+-rf\s+(?:/|~|/root|/home|/etc|/var|/usr|/boot|/opt|/srv)\b', "rm -rf 危险目录"),
    (r'\brm\s+-rf\s+\*\s*$', "rm -rf *"),
    (r'\bmkfs\b', "格式化文件系统"),
    (r'>\s*/dev/(sd|nvme|hd|mmcblk|vd|xvd)[a-z0-9]*', "写入原始块设备"),
    (r'\bdd\s+if=.*\s+of=/dev/', "dd 写入块设备"),
    (r':\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:', "fork bomb"),
    (r'\bkill\s+(-[^\s]+\s+)*-1\b', "kill 所有进程"),
    (r'(?:^|[;&|\n])\s*(shutdown|reboot|halt|poweroff)\b', "系统关机/重启"),
    (r'(?:^|[;&|\n])\s*init\s+[06]\b', "init 0/6"),
    (r'(?:^|[;&|\n])\s*systemctl\s+(poweroff|reboot|halt|kexec)\b', "systemctl 关机/重启"),
    (r'\bDROP\s+(TABLE|DATABASE)\b', "DROP TABLE/DATABASE"),
    (r'\bTRUNCATE\s+(TABLE\s+)?', "TRUNCATE 清空表"),
    (r'\bDELETE\s+FROM\b(?![^\n]*\bWHERE\b)', "DELETE 无 WHERE"),
]

_RE_FLAGS = re.IGNORECASE | re.DOTALL
HARDLINE_PATTERNS_COMPILED = [
    (re.compile(pattern, _RE_FLAGS), description)
    for pattern, description in HARDLINE_PATTERNS
]


def detect_hardline_command(command: str) -> tuple[bool, str | None]:
    normalized = command.lower()
    for pattern_re, description in HARDLINE_PATTERNS_COMPILED:
        if pattern_re.search(normalized):
            return True, description
    return False, None


# ============================================================================
# Sudo stdin 守卫
# ============================================================================

_SUDO_STDIN_RE = re.compile(
    r'(?:^|[;&|`\n]|&&|\|\||\$\()\s*sudo\s+-S\b',
    re.IGNORECASE,
)


def _check_sudo_stdin_guard(command: str) -> tuple[bool, str | None]:
    if "SUDO_PASSWORD" in os.environ:
        return False, None
    if _SUDO_STDIN_RE.search(command.lower()):
        return True, "sudo 密码猜测 (sudo -S)"
    return False, None


# ============================================================================
# 危险模式检测
# ============================================================================

DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r'\brm\s+', "rm 删除文件"),
    (r'\bchmod\s+[0-7]*7[0-7]*\b', "chmod 危险权限"),
    (r'\bchown\b', "chown 变更所有者"),
    (r'\bgit\s+reset\s+--hard\b', "git reset --hard"),
    (r'\bgit\s+push\b.*--force', "git force push"),
    (r'\bgit\s+branch\s+-D\b', "git branch 强制删除"),
    (r'\bsudo\b', "sudo 提权"),
    (r'\bnc\s+-[l]', "nc 监听端口"),
    (r'\bdocker\s+(rm|stop|kill|restart|system\s+prune)\b', "docker 危险操作"),
    (r'\bkubectl\s+(delete|apply|scale|rollout)\b', "kubectl 危险操作"),
    (r'\bDELETE\s+FROM\b', "DELETE 数据库操作"),
    (r'\bDROP\s+(TABLE|DATABASE|INDEX)\b', "DROP 数据库对象"),
    (r'\bUPDATE\s+\w+\s+SET\b(?![^\n]*\bWHERE\b)', "UPDATE 无 WHERE"),
    (r'\bALTER\s+TABLE\b', "ALTER TABLE"),
    (r'\bTRUNCATE\b', "TRUNCATE 清空表"),
    (r'清仓|全部卖出|全部清仓|all\s*(out|sell)', "清仓操作"),
    (r'(?:使用|进行|开启|申请|操作).*(?:杠杆|融资|margin|lending)', "杠杆/融资操作"),
    (r'修改.*风控|变更.*阈值|调整.*限额', "修改风控参数"),
    (r'prod.*(?:连接|数据库|database)|production.*(?:连接|connect)', "生产环境连接"),
]

DANGEROUS_PATTERNS_COMPILED = [
    (re.compile(pattern, _RE_FLAGS), description)
    for pattern, description in DANGEROUS_PATTERNS
]


def detect_dangerous_command(command: str) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    normalized = command.lower()
    for pattern_re, description in DANGEROUS_PATTERNS_COMPILED:
        if pattern_re.search(normalized):
            matches.append((description, description))
    return matches


# ============================================================================
# 审批决策
# ============================================================================


@dataclass
class ApprovalDecision:
    approved: bool
    reason: str = ""
    require_user: bool = False
    pattern_key: str = ""
    command: str = ""


@dataclass
class ApprovalConfig:
    mode: ApprovalMode = ApprovalMode.MANUAL
    timeout: int = 60
    cron_mode: str = "deny"
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: dict | None) -> "ApprovalConfig":
        if not data:
            return cls()
        mode = data.get("mode", "manual")
        if isinstance(mode, str):
            try:
                mode = ApprovalMode(mode.lower())
            except ValueError:
                mode = ApprovalMode.MANUAL
        return cls(
            mode=mode,
            timeout=int(data.get("timeout", 60)),
            cron_mode=str(data.get("cron_mode", "deny")),
            allow=[str(x) for x in (data.get("allow") or [])],
            deny=[str(x) for x in (data.get("deny") or [])],
        )


# ============================================================================
# 审批回调
# ============================================================================

_approval_callbacks: dict[str, Callable] = {}
_approval_lock = threading.Lock()


def register_approval_callback(session_id: str, callback: Callable) -> None:
    with _approval_lock:
        _approval_callbacks[session_id] = callback


def unregister_approval_callback(session_id: str) -> None:
    with _approval_lock:
        _approval_callbacks.pop(session_id, None)


# ============================================================================
# 主审批检查
# ============================================================================


def check_all_command_guards(
    command: str,
    session_id: str = "",
    config: ApprovalConfig | None = None,
) -> ApprovalDecision:
    cfg = config or ApprovalConfig()

    is_hardline, hardline_desc = detect_hardline_command(command)
    if is_hardline:
        logger.warning(f"[Approval] Hardline 阻断: {hardline_desc}")
        return ApprovalDecision(approved=False, reason=f"Hardline 阻断: {hardline_desc}", command=command)

    is_sudo_stdin, sudo_desc = _check_sudo_stdin_guard(command)
    if is_sudo_stdin:
        logger.warning(f"[Approval] Sudo stdin 阻断: {sudo_desc}")
        return ApprovalDecision(approved=False, reason=f"Sudo stdin 阻断: {sudo_desc}", command=command)

    deny_match = _match_user_deny_rule(command, cfg)
    if deny_match:
        logger.warning(f"[Approval] 用户 deny 规则阻断: {deny_match}")
        return ApprovalDecision(approved=False, reason=f"用户 deny: {deny_match}", command=command)

    if cfg.mode == ApprovalMode.OFF:
        return ApprovalDecision(approved=True, reason="审批模式: off")

    if _match_user_allow_rule(command, cfg):
        return ApprovalDecision(approved=True, reason="用户 allow 白名单")

    dangerous_matches = detect_dangerous_command(command)
    if not dangerous_matches:
        return ApprovalDecision(approved=True, reason="未检测到危险模式")

    pattern_desc = dangerous_matches[0][1]

    if cfg.mode == ApprovalMode.SMART:
        return _smart_approve(command, pattern_desc, session_id, cfg)

    return ApprovalDecision(
        approved=False,
        require_user=True,
        reason=f"危险操作: {pattern_desc}",
        pattern_key=pattern_desc,
        command=command,
    )


def _match_user_deny_rule(command: str, config: ApprovalConfig) -> str | None:
    if not config.deny:
        return None
    for pattern in config.deny:
        if fnmatch.fnmatchcase(command.lower(), pattern.lower()):
            return pattern
    return None


def _match_user_allow_rule(command: str, config: ApprovalConfig) -> bool:
    if not config.allow:
        return False
    for pattern in config.allow:
        if fnmatch.fnmatchcase(command.lower(), pattern.lower()):
            return True
    return False


def _smart_approve(
    command: str,
    pattern_desc: str,
    session_id: str,
    config: ApprovalConfig,
) -> ApprovalDecision:
    low_risk = [
        r'\b(status|ls|cat|head|tail|grep|echo|whoami|pwd|date|hostname|uname|df|du|free|ps|top|uptime)\b',
    ]
    cmd_lower = command.lower()
    for indicator in low_risk:
        if re.search(indicator, cmd_lower):
            return ApprovalDecision(approved=True, reason=f"Smart 自动通过: {pattern_desc} (低风险)")
    return ApprovalDecision(
        approved=False,
        require_user=True,
        reason=f"Smart 升级: {pattern_desc}",
        pattern_key=pattern_desc,
        command=command,
    )


# ============================================================================
# 审批请求等待
# ============================================================================

_pending_approvals: dict[str, threading.Event] = {}
_pending_results: dict[str, bool] = {}
_pending_lock = threading.Lock()


def request_approval(
    session_id: str,
    command: str,
    description: str,
    timeout: float = 60.0,
) -> bool:
    approval_id = f"{session_id}_{id(command)}"
    event = threading.Event()
    with _pending_lock:
        _pending_approvals[approval_id] = event
        _pending_results[approval_id] = False
    approved = event.wait(timeout=timeout)
    with _pending_lock:
        result = _pending_results.pop(approval_id, False)
        _pending_approvals.pop(approval_id, None)
    if not approved:
        logger.warning(f"[Approval] 审批超时或拒绝: {description}")
        return False
    return result


def resolve_approval(approval_id: str, approved: bool) -> None:
    with _pending_lock:
        if approval_id in _pending_approvals:
            _pending_results[approval_id] = approved
            _pending_approvals[approval_id].set()


# ============================================================================
# APPROVAL_PENDING - 供 API 层使用的简化审批字典
# ============================================================================

APPROVAL_PENDING: dict[str, bool] = {}