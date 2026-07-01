from tools.base_tool import BaseTool
from tools.tool_registry import registry
from core.sub_agent import spawn_subagent

class TaskTool(BaseTool):
    name = "task"
    description = (
        "启动一个子代理处理复杂子任务。子代理拥有独立的上下文，"
        "不会污染主对话，只返回最终结论。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "发给子代理的详细任务描述",
            },
        },
        "required": ["description"]
    }

    def run(self, description: str) -> str:
        return spawn_subagent(description)
    
registry.register(TaskTool)