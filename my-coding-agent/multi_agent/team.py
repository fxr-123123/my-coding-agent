import json
import time
import threading
from pathlib import Path
from dataclasses import dataclass, field
import random
from task.task_manager import TASKS_DIR, can_start

WORKDIR = Path.cwd()
MAILBOX_DIR = WORKDIR / ".mailboxes"
MAILBOX_DIR.mkdir(exist_ok=True)


class MessageBus:
    """基于文件的简单消息总线，每 agent 一个 .jsonl 信箱。
    read_inbox 是破坏性读取（读后即删）。"""

    def send(self, from_agent: str, to_agent: str, content: str,
             msg_type: str = "message", metadata: dict = None):
        msg = {
            "from": from_agent, "to": to_agent,
            "content": content, "type": msg_type,
            "ts": time.time(), "metadata": metadata or {},
        }
        inbox = MAILBOX_DIR / f"{to_agent}.jsonl"
        with open(inbox, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        print(f"  \033[33m[bus] {from_agent} → {to_agent}: "
              f"({msg_type}) {content[:60]}\033[0m")


    def read_inbox(self, agent: str) -> list[dict]:
        inbox = MAILBOX_DIR / f"{agent}.jsonl"
        if not inbox.exists():
            return []
        msgs = [json.loads(line) for line
                in inbox.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        inbox.unlink()
        return msgs


BUS = MessageBus()
active_teammates: dict[str, bool] = {}

# ── Autonomous Agent ──

IDLE_POLL_INTERVAL = 5
IDLE_TIMEOUT = 60


def scan_unclaimed_tasks() -> list[dict]:
    """找到所有 pending、无 owner、依赖已满足的任务"""
    unclaimed = []
    for f in sorted(TASKS_DIR.glob("task_*.json")):
        try:
            task = json.loads(f.read_text(encoding="utf-8"))
            if (task.get("status") == "pending"
                    and not task.get("owner")
                    and can_start(task["id"])):
                unclaimed.append(task)
        except Exception:
            pass
    return unclaimed


def idle_poll(agent_name: str, messages: list,
              name: str) -> str:
    """IDLE 阶段轮询 60 秒。返回 'work'、'shutdown' 或 'timeout'。"""
    for _ in range(IDLE_TIMEOUT // IDLE_POLL_INTERVAL):
        time.sleep(IDLE_POLL_INTERVAL)

        # 检查 inbox
        inbox = BUS.read_inbox(agent_name)
        if inbox:
            for msg in inbox:
                if msg.get("type") == "shutdown_request":
                    req_id = msg.get("metadata", {}).get("request_id", "")
                    BUS.send(name, "lead", "Shutting down gracefully.",
                             "shutdown_response",
                             {"request_id": req_id, "approve": True})
                    print(f"  \033[35m[protocol] {name} approved shutdown "
                          f"in idle ({req_id})\033[0m")
                    return "shutdown"
            # 非协议消息：注入并恢复工作
            messages.append({"role": "user",
                "content": "<inbox>" + json.dumps(inbox, ensure_ascii=False) + "</inbox>"})
            print(f"  \033[36m[idle] {name} found inbox messages\033[0m")
            return "work"

        # 扫描任务板
        unclaimed = scan_unclaimed_tasks()
        if unclaimed:
            task = unclaimed[0]
            from task.task_manager import claim_task as _claim_task
            result = _claim_task(task["id"], agent_name)
            if "Claimed" in result:
                wt_info = ""
                if task.get("worktree"):
                    from multi_agent.worktree import WORKTREES_DIR
                    wt_info = f"\nWork directory: {WORKTREES_DIR / task['worktree']}"
                messages.append({"role": "user",
                    "content": f"<auto-claimed>Task {task['id']}: "
                               f"{task['subject']}{wt_info}</auto-claimed>"})
                print(f"  \033[32m[idle] {name} auto-claimed: "
                      f"{task['subject']}\033[0m")
                return "work"
            print(f"  \033[33m[idle] {name} claim failed: {result}\033[0m")

    print(f"  \033[31m[idle] {name} timeout ({IDLE_TIMEOUT}s)\033[0m")
    return "timeout"


# ── Protocol State ──

@dataclass
class ProtocolState:
    request_id: str
    type: str       # "shutdown" | "plan_approval"
    sender: str
    target: str
    status: str     # pending | approved | rejected
    payload: str    # plan text or shutdown reason
    created_at: float = field(default_factory=time.time)


pending_requests: dict[str, ProtocolState] = {}


def new_request_id() -> str:
    return f"req_{random.randint(0, 999999):06d}"


def match_response(request_id: str, approve: bool):
    state = pending_requests.get(request_id)
    if not state:
        print(f"  \033[31m[protocol] unknown request_id: {request_id}\033[0m")
        return
    if state.status != "pending":
        print(f"  \033[33m[protocol] {request_id} already {state.status}\033[0m")
        return
    state.status = "approved" if approve else "rejected"
    icon = "✓" if approve else "✗"
    color = "32" if approve else "31"
    print(f"  \033[{color}m[protocol] {state.type} {icon} "
          f"({request_id}: {state.status})\033[0m")
    

def consume_lead_inbox(route_protocol: bool = True) -> list[dict]:
    """统一入口：读 lead 信箱，路由协议消息，返回所有消息"""
    msgs = BUS.read_inbox("lead")
    if not msgs:
        return []
    if route_protocol:
        for msg in msgs:
            meta = msg.get("metadata", {})
            req_id = meta.get("request_id", "")
            msg_type = msg.get("type", "")
            if req_id and msg_type.endswith("_response"):
                approve = meta.get("approve", False)
                match_response(req_id, approve)
    return msgs


def spawn_teammate_thread(name: str, role: str, prompt: str) -> str:
    """在后台线程中启动队友 agent，最多 10 轮，完成后发送摘要到 lead"""
    import os
    from anthropic import Anthropic

    if name in active_teammates:
        return f"Teammate '{name} already exists"
    
    system = (
        f"You are '{name}', a {role}. "
        f"Work directory: {WORKDIR}. "
        f"You are a TOOL-ONLY agent. You CANNOT output text. "
        f"Your ONLY way to communicate is by calling tools. "
        f"If you output text, you FAIL. Use send_message to speak."
    )
    client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))

    sub_tools = [
        {"name": "bash", "description": "Run a shell command.",
         "input_schema": {"type": "object",
                          "properties": {"command": {"type": "string"}},
                          "required": ["command"]}},
        {"name": "read_file", "description": "Read file contents.",
         "input_schema": {"type": "object",
                          "properties": {"path": {"type": "string"}},
                          "required": ["path"]}},
        {"name": "write_file", "description": "Write content to a file.",
         "input_schema": {"type": "object",
                          "properties": {"path": {"type": "string"},
                                         "content": {"type": "string"}},
                          "required": ["path", "content"]}},
        {"name": "send_message",
         "description": "Send a message to another agent.",
         "input_schema": {"type": "object",
                          "properties": {"to": {"type": "string"},
                                         "content": {"type": "string"}},
                          "required": ["to", "content"]}},
        {"name": "submit_plan",
         "description": "Submit a plan for Lead approval before executing.",
         "input_schema": {"type": "object",
                          "properties": {"plan": {"type": "string"}},
                          "required": ["plan"]}},
        {"name": "list_tasks", "description": "List all tasks on the board.",
         "input_schema": {"type": "object", "properties": {}, "required": []}},
        {"name": "claim_task", "description": "Claim a pending task.",
         "input_schema": {"type": "object",
                        "properties": {"task_id": {"type": "string"}},
                        "required": ["task_id"]}},
        {"name": "complete_task", "description": "Mark an in-progress task as completed.",
         "input_schema": {"type": "object",
                        "properties": {"task_id": {"type": "string"}},
                        "required": ["task_id"]}},
    ]


    def handle_inbox_message(msg: dict, messages: list) -> bool:
        """分发协议消息。返回 True 表示队友应停止。"""
        msg_type = msg.get("type", "message")
        meta = msg.get("metadata", {})
        req_id = meta.get("request_id", "")

        if msg_type == "shutdown_request":
            BUS.send(name, "lead", "Shutting down gracefully.",
                     "shutdown_response",
                     {"request_id": req_id, "approve": True})
            print(f"  \033[35m[protocol] {name} approved shutdown ({req_id})\033[0m")
            return True

        if msg_type == "plan_approval_response":
            approve = meta.get("approve", False)
            if approve:
                messages.append({"role": "user",
                                 "content": "[Plan approved] Proceed with the task."})
            else:
                messages.append({"role": "user",
                                 "content": f"[Plan rejected] Feedback: {msg['content']}"})

        return False


    def run():
        from tools.tool_registry import registry

        messages = [{"role": "user", "content": prompt}]

        from multi_agent.worktree import WORKTREES_DIR, get_worktree_path
        wt_ctx = {"path": None}

        def _wt_cwd():
            p = wt_ctx["path"]
            return Path(p) if p else None

        def _run_bash(command: str) -> str:
            import subprocess
            cwd = _wt_cwd() or WORKDIR
            try:
                r = subprocess.run(command, shell=True, cwd=cwd,
                                   capture_output=True, text=True, timeout=120,
                                   encoding="utf-8", errors="replace")
                out = ((r.stdout or "") + (r.stderr or "")).strip()
                return out[:50000] if out else "(no output)"
            except subprocess.TimeoutExpired:
                return "Error: Timeout (120s)"
            
        def _run_read_file(path: str) -> str:
            try:
                cwd = _wt_cwd() or WORKDIR
                fp = (cwd / path).resolve()
                if not fp.is_relative_to(cwd):
                    return f"Error: Path escapes workspace: {path}"
                return fp.read_text(encoding="utf-8")[:50000]
            except Exception as e:
                return f"Error: {e}"

        def _run_write_file(path: str, content: str) -> str:
            try:
                cwd = _wt_cwd() or WORKDIR
                fp = (cwd / path).resolve()
                if not fp.is_relative_to(cwd):
                    return f"Error: Path escapes workspace: {path}"
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(content, encoding="utf-8")
                return f"Wrote {len(content)} bytes to {path}"
            except Exception as e:
                return f"Error: {e}"

        def _run_list_tasks():
            from task.task_manager import list_tasks as _list_task_func
            tasks = _list_task_func()
            if not tasks:
                return "No tasks."
            return "\n".join(
                f"  {t.id}: {t.subject} [{t.status}]" for t in tasks)

        def _run_claim_task(task_id: str):
            from task.task_manager import claim_task as _ct, load_task
            result = _ct(task_id, owner=name)
            if "Claimed" in result:
                task = load_task(task_id)
                if task.worktree:
                    wt_ctx["path"] = str(WORKTREES_DIR / task.worktree)
                else:
                    wt_ctx["path"] = None
            return result

        def _run_complete_task(task_id: str):
            from task.task_manager import complete_task as _cpt
            result = _cpt(task_id)
            wt_ctx["path"] = None
            return result


        while True:
            # 身份重新注入（消息少时）
            if len(messages) <= 3:
                messages.insert(0, {"role": "user",
                    "content": f"<identity>You are '{name}', role: {role}. "
                               f"Continue your work.</identity>"})

            # ── WORK 阶段（最多 10 轮）──
            should_shutdown = False
            for _ in range(10):
                # 检查收件箱
                inbox = BUS.read_inbox(name)
                if inbox:
                    non_protocol = []
                    for msg in inbox:
                        if msg.get("type") in ("shutdown_request", "plan_approval_response"):
                            if handle_inbox_message(msg, messages):
                                should_shutdown = True
                                break
                        else:
                            non_protocol.append(msg)
                    if should_shutdown:
                        break
                    if non_protocol:
                        messages.append({"role": "user",
                        "content": "<inbox>" + json.dumps(non_protocol, ensure_ascii=False) + "</inbox>"})
            
                # LLM turn
                try:
                    response = client.messages.create(
                        model=os.environ["MODEL_ID"],
                        system=system, messages=messages[-20:],
                        tools=sub_tools, max_tokens=8000,
                    )
                except Exception as e:
                    print(f"  \033[31m[teammate error] {e}\033[0m")
                    break

                messages.append({"role": "assistant", "content": response.content})
                
                if response.stop_reason != "tool_use":
                    break

                # 执行工具
                results = []
                for block in response.content:
                    if block.type == "tool_use":
                        if block.name == "send_message":
                            BUS.send(name, block.input.get("to", "lead"),
                                    block.input.get("content", ""))
                            output = "Sent"
                        elif block.name == "submit_plan":
                            plan = block.input.get("plan", "")
                            req_id = new_request_id()
                            pending_requests[req_id] = ProtocolState(
                                request_id=req_id, type="plan_approval",
                                sender=name, target="lead",
                                status="pending", payload=plan,
                            )
                            BUS.send(name, "lead", plan, "plan_approval_request",
                                    {"request_id": req_id})
                            output = f"Plan submitted ({req_id}). Waiting for approval..."
                        elif block.name == "bash":
                            output = _run_bash(block.input.get("command", ""))
                        elif block.name == "read_file":
                            output = _run_read_file(block.input.get("path", ""))
                        elif block.name == "write_file":
                            output = _run_write_file(
                                block.input.get("path", ""),
                                block.input.get("content", ""))
                        elif block.name == "list_tasks":
                            output = _run_list_tasks()
                        elif block.name == "claim_task":
                            output = _run_claim_task(block.input.get("task_id", ""))
                        elif block.name == "complete_task":
                            output = _run_complete_task(block.input.get("task_id", ""))
                        else:
                            output = registry.run_tool(block.name, block.input)
                        results.append({"type": "tool_result",
                                        "tool_use_id": block.id,
                                        "content": str(output)})
                messages.append({"role": "user", "content": results})

            if should_shutdown:
                break

            # ── IDLE 阶段 ──
            idle_result = idle_poll(name, messages, name)
            if idle_result == "shutdown":
                should_shutdown = True
                break
            if idle_result == "timeout":
                break

        # 发送最终摘要
        summary = "Done."
        for msg in reversed(messages):
            if msg["role"] == "assistant" and isinstance(msg["content"], list):
                for b in msg["content"]:
                    t = getattr(b, "text", None)
                    if t:
                        summary = t
                        break
                if summary != "Done.":
                    break
        BUS.send(name, "lead", summary, "result")
        active_teammates.pop(name, None)
        print(f"  \033[32m[teammate] {name} finished\033[0m")

    active_teammates[name] = True
    threading.Thread(target=run, daemon=True).start()
    print(f"  \033[36m[teammate] {name} spawned as {role}\033[0m")
    return f"Teammate '{name}' spawned as {role}"