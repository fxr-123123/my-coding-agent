from tools.base_tool import BaseTool
from tools.tool_registry import registry
from task.task_manager import (
    create_task, list_tasks, get_task, claim_task, complete_task,
)


class CreateTaskTool(BaseTool):
    name = "create_task"
    description = "创建新任务，可选 blockedBy 依赖"
    input_schema = {
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "任务主题"},
            "description": {"type": "string", "description": "详细描述"},
            "blockedBy": {
                "type": "array",
                "items": {"type": "string"},
                "description": "依赖的任务 ID 列表",
            },
        },
        "required": ["subject"],
    }

    def run(self, subject: str, description: str = "",
            blockedBy: list[str] | None = None) -> str:
        task = create_task(subject, description, blockedBy)
        deps = f" (blockedBy: {', '.join(blockedBy)})" if blockedBy else ""
        print(f"  \033[34m[create] {task.subject}{deps}\033[0m")
        return f"Created {task.id}: {task.subject}{deps}"


class ListTasksTool(BaseTool):
    name = "list_tasks"
    description = "列出所有任务及状态"
    input_schema = {"type": "object", "properties": {}, "required": []}

    def run(self) -> str:
        tasks = list_tasks()
        if not tasks:
            return "No tasks. Use create_task to add some."
        lines = []
        for t in tasks:
            icon = {"pending": "○", "in_progress": "●",
                    "completed": "✓"}.get(t.status, "?")
            deps = f" (blockedBy: {', '.join(t.blockedBy)})" if t.blockedBy else ""
            owner = f" [{t.owner}]" if t.owner else ""
            lines.append(
                f"  {icon} {t.id}: {t.subject} [{t.status}]{owner}{deps}"
            )
        return "\n".join(lines)


class GetTaskTool(BaseTool):
    name = "get_task"
    description = "根据 ID 获取任务详情"
    input_schema = {
        "type": "object",
        "properties": {"task_id": {"type": "string"}},
        "required": ["task_id"],
    }

    def run(self, task_id: str) -> str:
        try:
            return get_task(task_id)
        except FileNotFoundError:
            return f"Error: Task {task_id} not found"


class ClaimTaskTool(BaseTool):
    name = "claim_task"
    description = "认领 pending 任务，状态变为 in_progress"
    input_schema = {
        "type": "object",
        "properties": {"task_id": {"type": "string"}},
        "required": ["task_id"],
    }

    def run(self, task_id: str) -> str:
        return claim_task(task_id, owner="agent")
    

class CompleteTaskTool(BaseTool):
    name = "complete_task"
    description = "完成 in_progress 任务，自动通知被解锁的下游任务"
    input_schema = {
        "type": "object",
        "properties": {"task_id": {"type": "string"}},
        "required": ["task_id"],
    }

    def run(self, task_id: str) -> str:
        return complete_task(task_id)
    

registry.register(CreateTaskTool)
registry.register(ListTasksTool)
registry.register(GetTaskTool)
registry.register(ClaimTaskTool)
registry.register(CompleteTaskTool)