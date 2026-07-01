from tools.base_tool import BaseTool
from tools.tool_registry import registry
from multi_agent.worktree import create_worktree, remove_worktree, keep_worktree


class CreateWorktreeTool(BaseTool):
    name = "create_worktree"
    description = "创建隔离的 git worktree，可选绑定到任务"
    input_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "worktree 名称"},
            "task_id": {"type": "string", "description": "绑定的任务 ID"},
        },
        "required": ["name"],
    }
    def run(self, name: str, task_id: str = "") -> str:
        return create_worktree(name, task_id)


class RemoveWorktreeTool(BaseTool):
    name = "remove_worktree"
    description = "删除 worktree。有未提交更改时需设 discard_changes=true"
    input_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "discard_changes": {"type": "boolean"},
        },
        "required": ["name"],
    }
    def run(self, name: str, discard_changes: bool = False) -> str:
        return remove_worktree(name, discard_changes)
    

class KeepWorktreeTool(BaseTool):
    name = "keep_worktree"
    description = "保留 worktree 供人工审查，分支不删除"
    input_schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    def run(self, name: str) -> str:
        return keep_worktree(name)
    

registry.register(CreateWorktreeTool)
registry.register(RemoveWorktreeTool)
registry.register(KeepWorktreeTool)