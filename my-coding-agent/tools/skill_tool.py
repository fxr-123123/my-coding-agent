from tools.base_tool import BaseTool
from tools.tool_registry import registry
from core.skill_loader import load_skill

class LoadSkillTool(BaseTool):
    name = "load_skill"
    description = "加载指定技能的完整内容。技能名称可通过系统提示中的技能目录查看。"
    input_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "技能名称"}
        },
        "required": ["name"],
    }

    def run(self, name: str) -> str:
        return load_skill(name)
    
registry.register(LoadSkillTool)