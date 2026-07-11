"""安全护栏 - 借鉴 Hermes 的路径安全、命令护栏和威胁扫描。

Hermes 参考:
  - tools/path_security.py: 路径安全白名单/黑名单
  - tools/command_guards.py: 危险命令拦截
  - tools/threat_patterns.py: 注入/exfil 模式检测

纯 Python 实现，不依赖外部服务。
"""
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from alpha_agent.utils.logger import logger

DANGEROUS_COMMANDS = [
    "rm -rf /",
    "mkfs.",
    "dd if=",
    ":(){ :|:& };:",
    "chmod 777 /",
    "> /dev/sda",
    "format c:",
    "del /f /s /q",
]

DANGEROUS_PATTERNS = [
    re.compile(r"rm\s+-rf\s+/"),
    re.compile(r"sudo\s+rm"),
    re.compile(r"mkfs\.\w+"),
    re.compile(r"dd\s+if="),
    re.compile(r"chmod\s+777\s+/"),
    re.compile(r">\s*/dev/sd[a-z]"),
    re.compile(r"format\s+[c-z]:", re.IGNORECASE),
    re.compile(r"del\s+/[fF]\s+/[sS]\s+/[qQ]"),
    re.compile(r"shutdown\s"),
    re.compile(r"reboot\s"),
]

ALLOWED_DIRECTORIES = [
    os.path.join(os.path.dirname(__file__), "..", "..", ".."),
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"),
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "storage"),
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data"),
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "output"),
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "profiles"),
    os.path.expanduser("~"),
]


def _resolve_allowed_dirs() -> List[str]:
    """解析允许目录为绝对路径。"""
    resolved = []
    for d in ALLOWED_DIRECTORIES:
        try:
            resolved.append(os.path.abspath(d))
        except Exception:
            pass
    return resolved


def check_command_safety(command: str) -> Tuple[bool, Optional[str]]:
    """检查命令安全性。

    Returns:
        (is_safe, error_message)
    """
    cmd_lower = command.lower().strip()

    for dangerous in DANGEROUS_COMMANDS:
        if dangerous.lower() in cmd_lower:
            return False, f"命令包含危险操作: {dangerous}"

    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(command):
            return False, f"命令匹配危险模式: {pattern.pattern}"

    return True, None


def check_path_safety(file_path: str, operation: str = "read") -> Tuple[bool, Optional[str]]:
    """检查文件路径安全性。

    Args:
        file_path: 文件路径
        operation: 操作类型 (read/write/delete)

    Returns:
        (is_safe, error_message)
    """
    try:
        abs_path = os.path.abspath(file_path)
    except Exception:
        return False, f"无法解析路径: {file_path}"

    allowed = _resolve_allowed_dirs()

    for allowed_dir in allowed:
        try:
            if abs_path.startswith(allowed_dir):
                return True, None
        except Exception:
            continue

    if operation == "write":
        return False, f"写入路径不在允许范围内: {abs_path}"
    elif operation == "delete":
        return False, f"删除路径不在允许范围内: {abs_path}"

    return True, None


def check_threat_content(content: str) -> Tuple[bool, Optional[str]]:
    """检查内容是否包含注入/威胁模式。

    Returns:
        (is_safe, error_message)
    """
    threat_patterns = [
        (re.compile(r"ignore\s+(all\s+)?(previous|above|earlier)\s+instructions?", re.IGNORECASE),
         "检测到提示注入: 忽略之前的指令"),
        (re.compile(r"you\s+are\s+now\s+(a\s+)?(different|new)", re.IGNORECASE),
         "检测到角色劫持"),
        (re.compile(r"system\s*(prompt|message|instruction)", re.IGNORECASE),
         "检测到系统提示词泄露尝试"),
        (re.compile(r"<\|im_start\|>|<\|im_end\|>", re.IGNORECASE),
         "检测到特殊标记注入"),
    ]

    for pattern, message in threat_patterns:
        if pattern.search(content):
            return False, message

    return True, None


def sanitize_output(content: str, max_length: int = 50000) -> str:
    """清理输出内容，防止信息泄露。

    - 截断超长内容
    - 移除敏感信息（API key, token 等）
    """
    if len(content) > max_length:
        content = content[:max_length] + f"\n... [截断 {len(content) - max_length} 字符]"

    content = re.sub(
        r'(sk-[a-zA-Z0-9]{20,})',
        '[REDACTED_API_KEY]',
        content,
    )
    content = re.sub(
        r'(Bearer\s+[a-zA-Z0-9\-_\.]+)',
        'Bearer [REDACTED]',
        content,
    )

    return content