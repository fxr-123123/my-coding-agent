from tools.base_tool import BaseTool
from tools.tool_registry import registry
from core.todo_plan import TodoPlan, TodoItem, set_todo, get_todo, print_todo

class TodoWriteTool(BaseTool):
    name = "todo_write"
    description = (
        "创建或更新任务计划。首次调用时列出所有步骤，"
        "之后每完成一步或开始新步骤时调用更新状态。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "description": "待办步骤列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "步骤描述"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "doing", "done"],
                            "description": "步骤状态"
                        },
                    },
                    "required": ["content", "status"]
                },
            }
        },
        "required": ["steps"],
    }

    def run(self, steps: list) -> str:
        items = []
        current = 0
        for i, s in enumerate(steps, start=1):
            items.append(TodoItem(step_id=i, content=s["content"], status=s["status"]))
            if s["status"] == "doing":
                current = i
        plan = TodoPlan(
            total_steps=len(items),
            steps=items,
            current_step=current or 1,
            is_completed=all(s.status == "done" for s in items),
        )
        set_todo(plan)
        print_todo(plan)
        done = sum(1 for s in items if s.status == "done")
        return f"计划已更新 ({done}/{len(items)} 完成)"

registry.register(TodoWriteTool)