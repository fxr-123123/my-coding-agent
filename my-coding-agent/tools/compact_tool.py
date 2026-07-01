from tools.base_tool import BaseTool
from tools.tool_registry import registry
from core.context_compact import compact_history


class CompactTool(BaseTool):
    name = "compact"
    description = "压缩对话历史以释放上下文空间，LLM自动摘要保留关键信息。"
    input_schema = {
        "type": "object",
        "properties": {
            "focus": {
                "type": "string",
                "description": "摘要时应重点关注的内容（可选）",
            },
        },
    }

    def run(self, focus: str = "") -> str:
        return "[Compacted. Conversation history has been summarized.]"
    
registry.register(CompactTool)