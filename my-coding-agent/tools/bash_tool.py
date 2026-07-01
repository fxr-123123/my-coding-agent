import subprocess
import os
from tools.base_tool import BaseTool
from tools.tool_registry import registry

class BashTool(BaseTool):
    name = "bash"
    description = "Run a shell command in the current workspace."
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "run_in_background": {"type": "boolean"},
        },
        "required": ["command"],
    }

    def run(self, command: str, run_in_background: bool = False) -> str:
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
                timeout=120,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            return "Error: Timeout (120s)"
        except (FileNotFoundError, OSError) as e:
            return f"Error: {e}"
        output = ((result.stdout or "") + (result.stderr or "")).strip()
        return output[:50000] if output else "(no output)"
    
registry.register(BashTool)