import threading

_bg_counter = 0
background_tasks: dict[str, dict] = {}
background_results: dict[str, str] = {}
background_lock = threading.Lock()


def is_slow_operation(tool_name: str, tool_input: dict) -> bool:
    """启发式判断：命令是否可能超过 30 秒"""
    if tool_name != "bash":
        return False
    cmd = tool_input.get("command", "").lower()
    slow_keywords = [
        "install", "build", "test", "deploy", "compile",
        "docker build", "pip install", "npm install",
        "cargo build", "pytest", "make",
    ]
    return any(kw in cmd for kw in slow_keywords)


def should_run_background(tool_name: str, tool_input: dict) -> bool:
    """模型显式要求优先；否则启发式判断"""
    if tool_input.get("run_in_background"):
        return True
    return is_slow_operation(tool_name, tool_input)


def start_background_task(tool_name: str, tool_input: dict, execute_fn) -> str:
    """在 daemon 线程中执行工具，返回 bg_id"""
    global _bg_counter
    _bg_counter += 1
    bg_id = f"bg_{_bg_counter:04d}"
    cmd = tool_input.get("command", tool_name)

    def worker():
        result = execute_fn(tool_name, tool_input)
        with background_lock:
            background_tasks[bg_id]["status"] = "completed"
            background_results[bg_id] = result

    with background_lock:
        background_tasks[bg_id] = {
            "command": cmd,
            "status": "running",
        }
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    print(f"  \033[33m[background] dispatched {bg_id}: {cmd[:60]}\033[0m")
    return bg_id


def collect_background_results() -> list[str]:
    """收集已完成的后台结果，返回 <task_notification> 格式的消息列表"""
    with background_lock:
        ready_ids = [bid for bid, t in background_tasks.items()
                     if t["status"] == "completed"]
        
    notifications = []
    for bg_id in ready_ids:
        with background_lock:
            task = background_tasks.pop(bg_id)
            output = background_results.pop(bg_id, "")
        summary = output[:300]
        notifications.append(
            f"<task_notification>\n"
            f"  <task_id>{bg_id}</task_id>\n"
            f"  <status>completed</status>\n"
            f"  <command>{task['command']}</command>\n"
            f"  <summary>{summary}</summary>\n"
            f"</task_notification>"
        )
        print(f"  \033[32m[background done] {bg_id}: "
              f"{task['command'][:60]} ({len(output)} chars)\033[0m")
    return notifications