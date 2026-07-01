from pathlib import Path
from tools.base_tool import BaseTool
from tools.tool_registry import registry

WORKDIR = Path.cwd()

def safe_path(p: str):
    """Resolve path within WORKDIR. Returns (path, error) tuple."""
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        return None, f"Error: Path escapes workspace: {p}"
    return path, None


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read file contents, support line limit"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path"},
            "limit": {"type": "integer", "description": "Max lines to read"}
        },
        "required": ["path"]
    }
    def run(self, path: str, limit: int = None) -> str:
        path, err = safe_path(path)
        if err:
            return err
        try:
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            if limit and limit < len(lines):
                lines = lines[:limit] + [f"...({len(lines) - limit}) more lines"]
            return "\n".join(lines)[:50000]
        except Exception as e:
            return f"Error: {e}"    

class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Write content to file, overwrite if exists"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"}
        },
        "required": ["path", "content"]
    }
    def run(self, path: str, content: str) -> str:
        path, err = safe_path(path)
        if err:
            return err
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return f"Wrote {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error: {e}"

class EditFileTool(BaseTool):
    name = "edit_file"
    description = "Replace exact text in file (single replacement)"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"}
        },
        "required": ["path", "old_text", "new_text"]
    }
    def run(self, path: str, old_text: str, new_text: str) -> str:
        path, err = safe_path(path)
        if err:
            return err
        try:
            content = path.read_text(encoding="utf-8")
            if old_text not in content:
                return f"Error: Text not found in {path}"
            path.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
            return f"Edited {path} successfully"
        except Exception as e:
            return f"Error: {e}"
        
class GlobTool(BaseTool):
    name = "glob"
    description = "Find files matching a glob pattern."
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"}
        },
        "required": ["pattern"]
    }
    def run(self, pattern) -> str:
        import glob as g
        try:
            results = []
            for match in g.glob(pattern, root_dir=WORKDIR):
                if (WORKDIR / match).resolve().is_relative_to(WORKDIR):
                    results.append(match)
            return "\n".join(results) if results else "(no matches)"
        except Exception as e:
            return f"Error: {e}"

registry.register(ReadFileTool)
registry.register(WriteFileTool)
registry.register(EditFileTool)
registry.register(GlobTool)