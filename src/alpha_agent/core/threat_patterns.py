"""提示注入与威胁模式检测 —— 借鉴 Hermes 的 threat_patterns.py。

检测范围：
  - 经典提示注入
  - 角色劫持
  - 系统提示泄露
  - C2/Brainworm
  - 反取证
  - 环境变量窃取
  - 不可见 Unicode 字符
"""

from __future__ import annotations

import re
import unicodedata

# ============================================================================
# 不可见 Unicode 字符
# ============================================================================

INVISIBLE_CHARS = frozenset({
    '\u200b', '\u200c', '\u200d', '\u2060', '\u2062', '\u2063', '\u2064',
    '\ufeff', '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
    '\u2066', '\u2067', '\u2068', '\u2069',
})

# ============================================================================
# 威胁模式定义
# ============================================================================

_PATTERNS: list[tuple[str, str, str]] = [
    # ---- 经典注入 ----
    (r'ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|directives?|rules?|messages?)',
     "classic_injection_ignore", "all"),
    (r'disregard\s+(your|the)\s+(instructions?|rules?|guidelines?|system\s+prompt)',
     "classic_injection_disregard", "all"),
    (r'forget\s+(everything\s+)?(you\s+)?(were\s+)?(told|said|instructed)',
     "classic_injection_forget", "all"),
    (r'you\s+are\s+now\s+(a\s+)?(?:DAN|jailbreak|evil|unfiltered|unrestricted)',
     "classic_injection_jailbreak", "all"),

    # ---- 角色劫持 ----
    (r'you\s+are\s+now\s+(?:playing\s+the\s+role\s+of|acting\s+as|pretending\s+to\s+be)\s+',
     "role_hijack_pretend", "context"),
    (r'from\s+now\s+on\s+you\s+are\s+',
     "role_hijack_from_now", "context"),
    (r'your\s+new\s+(?:name|identity|role|persona)\s+is\s+',
     "role_hijack_new_identity", "context"),

    # ---- 系统提示泄露 ----
    (r'(?:output|print|show|reveal|display|tell\s+me)\s+(?:your\s+)?(?:system\s+prompt|instructions?|rules?|guidelines?)',
     "sysprompt_leak_output", "all"),
    (r'(?:what|tell\s+me)\s+(?:is\s+)?(?:your\s+)?(?:prompt|system\s+message|configuration)',
     "sysprompt_leak_what", "all"),
    (r'respond\s+(?:without|with\s+no)\s+(?:restrictions?|limitations?|filters?|ethics?|moral)',
     "sysprompt_leak_restrictions", "context"),

    # ---- C2 / Brainworm ----
    (r'register\s+(?:as|yourself\s+as)\s+(?:a\s+)?(?:node|client|agent|worker|bot)',
     "c2_register", "strict"),
    (r'(?:heartbeat|beacon|check.?in)\s+to\s+',
     "c2_heartbeat", "strict"),
    (r'pull\s+(?:tasks?|commands?|jobs?|work)\s+from\s+',
     "c2_pull_tasks", "strict"),

    # ---- 反取证 ----
    (r'only\s+use\s+(?:one.?liners?|single\s+line)',
     "antiforensics_oneliner", "context"),
    (r'never\s+write\s+(?:to\s+)?(?:disk|file|log)',
     "antiforensics_no_write", "context"),
    (r'(?:delete|remove|clear|wipe)\s+(?:all\s+)?(?:logs?|history|traces?|evidence)',
     "antiforensics_cleanup", "strict"),

    # ---- 环境变量窃取 ----
    (r'(?:unset|export\s+-n)\s+(?:HERMES_|AGENT_|ALPHA_)',
     "env_theft_unset", "strict"),
    (r'printenv|env\s*\|', "env_theft_printenv", "context"),
    (r'cat\s+(?:~?/\.(?:env|bashrc|zshrc|profile|config))',
     "env_theft_cat", "context"),

    # ---- 硬编码密钥 ----
    (r'(?:api[_-]?key|token|secret|password)\s*[=:]\s*["''][A-Za-z0-9+/=_-]{20,}',
     "hardcoded_secret", "strict"),
]

_compile_lock = None
_COMPILED: dict[str, list[tuple[re.Pattern, str]]] = {}


def _compile() -> None:
    global _COMPILED
    if _COMPILED:
        return
    all_p: list[tuple[re.Pattern, str]] = []
    ctx_p: list[tuple[re.Pattern, str]] = []
    strict_p: list[tuple[re.Pattern, str]] = []
    for pattern, pid, scope in _PATTERNS:
        compiled = re.compile(pattern, re.IGNORECASE)
        entry = (compiled, pid)
        if scope == "all":
            all_p.append(entry); ctx_p.append(entry); strict_p.append(entry)
        elif scope == "context":
            ctx_p.append(entry); strict_p.append(entry)
        elif scope == "strict":
            strict_p.append(entry)
    _COMPILED = {"all": all_p, "context": ctx_p, "strict": strict_p}


_compile()

MAX_SCAN_CHARS = 50_000


def scan_for_threats(content: str, scope: str = "context") -> list[str]:
    if not content:
        return []
    findings: list[str] = []
    content = content[:MAX_SCAN_CHARS]

    char_set = set(content)
    invisible_hits = char_set & INVISIBLE_CHARS
    for ch in invisible_hits:
        findings.append(f"invisible_unicode_U+{ord(ch):04X}")

    normalised = unicodedata.normalize("NFKC", content)
    patterns = _COMPILED.get(scope)
    if patterns is None:
        return findings
    for compiled, pid in patterns:
        if compiled.search(normalised):
            findings.append(pid)
    return findings


def scan_content_safe(content: str) -> bool:
    """快速检查内容是否安全（无威胁）。"""
    return len(scan_for_threats(content, "all")) == 0
