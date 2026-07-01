from pathlib import Path
from system.hook import register_hook

WORKDIR = Path.cwd()

# ── Gate 1: 硬黑名单 ──

DENY_LIST = [
    "rm -rf", "sudo", "shutdown", "reboot",
    "mkfs", "dd if=", "> /dev/sda",
]

def check_deny_list(tool_name: str, params: dict) -> str | None:
    """Gate 1: 永远禁止的操作"""
    if tool_name != "bash":
        return None
    command = params.get("command", "")
    for pattern in DENY_LIST:
        if pattern in command:
            return f"Blocked: '{pattern}' is on the deny list"
    return None


# ── Gate 2: 规则匹配 ──

PERMISSION_RULES = [
    {
        "tools": ["write_file", "edit_file"],
        "check": lambda args: _outside_workspace(args.get("path", "")),
        "message": "Writing outside workspace",
    },
    {
        "tools": ["bash"],
        "check": lambda args: _destructive_command(args.get("command", "")),
        "message": "Potentially destructive command",
    },
    {
        "tools": ["bash"],
        "check": lambda args: _outside_workspace_bash(args.get("command", "")),
        "message": "Shell command may write/access outside workspace",
    },
]

def _outside_workspace(path: str) -> bool:
    try:
        return not (WORKDIR / path).resolve().is_relative_to(WORKDIR)
    except ValueError:
        return True
    
def _destructive_command(command: str) -> bool:
    """检查是否存在潜在的破坏性操作"""
    dangerous = ["rm ", "> /etc/", "chmod 777", "del /f", "format "]
    return any(kw in command for kw in dangerous)

def _outside_workspace_bash(command: str) -> bool:
    """检查 bash 命令是否涉及工作区外路径"""
    import re
    # 匹配 Windows 路径或 > 重定向到非工作区的操作
    paths = re.findall(r'[A-Za-z]:[\\/][^\s]*', command)
    for p in paths:
        if _outside_workspace(p):
            return True
    return False

def check_rules(tool_name: str, params: dict) -> str | None:
    """Gate 2: 上下文相关的规则检查"""
    for rule in PERMISSION_RULES:
        if tool_name in rule["tools"] and rule["check"](params):
            return rule["message"]
    return None


# ── Gate 3: 用户确认 ──

def ask_user(tool_name: str, params: dict, reason: str) -> bool:
    """Gate 3: 触发规则后暂停，等待用户确认"""
    print(f"\n\033[33m⚠  {reason}\033[0m")
    print(f"   Tool: {tool_name}({params})")
    try:
        choice = input("   Allow? [y/N] ").strip().lower()
        return choice in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False
    

# ── 管道入口 ──

def permission_hook(block) -> str | None:
    """三级管道：任一 Gate 不通过返回 False"""
    # Gate 1: 黑名单
    reason = check_deny_list(block.name, block.input)
    if reason:
        print(f"\n\033[31m⛔ {reason}\033[0m")
        return "Permission denied."

    # Gate 2: 规则匹配
    reason = check_rules(block.name, block.input)
    if reason:
        # Gate 3: 用户确认
        if not ask_user(block.name, block.input, reason):
            return "Permission denied by user."

    return None  # 放行

register_hook("PreToolUse", permission_hook)