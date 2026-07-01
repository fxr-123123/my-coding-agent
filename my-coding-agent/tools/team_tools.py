from tools.base_tool import BaseTool
from tools.tool_registry import registry
from multi_agent.team import (
    spawn_teammate_thread, BUS, new_request_id, pending_requests,
    ProtocolState, consume_lead_inbox,
)


class SpawnTeammateTool(BaseTool):
    name = "spawn_teammate"
    description = "在后台线程中启动一个队友 agent"
    input_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "队友名称"},
            "role": {"type": "string", "description": "队友角色，如 code-reviewer"},
            "prompt": {"type": "string", "description": "发给队友的任务指令"},
        },
        "required": ["name", "role", "prompt"],
    }

    def run(self, name: str, role: str, prompt: str) -> str:
        return spawn_teammate_thread(name, role, prompt)
    

class SendMessageTool(BaseTool):
    name = "send_message"
    description = "通过 MessageBus 给队友发消息"
    input_schema = {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "接收者名称"},
            "content": {"type": "string", "description": "消息内容"},
        },
        "required": ["to", "content"],
    }

    def run(self, to: str, content: str) -> str:
        BUS.send("lead", to, content)
        return f"Sent to {to}"
    

class CheckInboxTool(BaseTool):
    name = "check_inbox"
    description = "查看 lead 信箱中队友发来的消息"
    input_schema = {"type": "object", "properties": {}, "required": []}

    def run(self) -> str:
        msgs = consume_lead_inbox(route_protocol=True)
        if not msgs:
            return "(inbox empty)"
        lines = []
        for m in msgs:
            lines.append(f"  [{m['from']}] {m['content'][:200]}")
        return "\n".join(lines)


class RequestShutdownTool(BaseTool):
    name = "request_shutdown"
    description = "请求队友优雅关闭"
    input_schema = {
        "type": "object",
        "properties": {"teammate": {"type": "string"}},
        "required": ["teammate"],
    }

    def run(self, teammate: str) -> str:
        req_id = new_request_id()
        pending_requests[req_id] = ProtocolState(
            request_id=req_id, type="shutdown",
            sender="lead", target=teammate,
            status="pending", payload="",
        )
        BUS.send("lead", teammate, "Please shut down gracefully.",
                 "shutdown_request", {"request_id": req_id})
        print(f"  \033[35m[protocol] shutdown_request → {teammate} ({req_id})\033[0m")
        return f"Shutdown request sent to {teammate} (req: {req_id})"


class RequestPlanTool(BaseTool):
    name = "request_plan"
    description = "要求队友提交执行计划供审批"
    input_schema = {
        "type": "object",
        "properties": {
            "teammate": {"type": "string"},
            "task": {"type": "string"},
        },
        "required": ["teammate", "task"],
    }

    def run(self, teammate: str, task: str) -> str:
        BUS.send("lead", teammate, f"Please submit a plan for: {task}", "message")
        return f"Asked {teammate} to submit a plan"
    

class ReviewPlanTool(BaseTool):
    name = "review_plan"
    description = "审批队友提交的计划，通过 request_id 关联"
    input_schema = {
        "type": "object",
        "properties": {
            "request_id": {"type": "string"},
            "approve": {"type": "boolean"},
            "feedback": {"type": "string"},
        },
        "required": ["request_id", "approve"],
    }

    def run(self, request_id: str, approve: bool, feedback: str = "") -> str:
        state = pending_requests.get(request_id)
        if not state:
            return f"Request {request_id} not found"
        if state.status != "pending":
            return f"Request {request_id} already {state.status}"
        state.status = "approved" if approve else "rejected"
        BUS.send("lead", state.sender, feedback or ("Approved" if approve else "Rejected"),
                 "plan_approval_response",
                 {"request_id": request_id, "approve": approve})
        return f"Plan {'approved' if approve else 'rejected'} ({request_id})"




registry.register(SpawnTeammateTool)
registry.register(SendMessageTool)
registry.register(CheckInboxTool)
registry.register(RequestShutdownTool)
registry.register(RequestPlanTool)
registry.register(ReviewPlanTool)