import re
import subprocess
import json
import time
from pathlib import Path

WORKDIR = Path.cwd()
WORKTREES_DIR = WORKDIR / ".worktrees"
WORKTREES_DIR.mkdir(exist_ok=True)
VALID_WT_NAME = re.compile(r'^[A-Za-z0-9._-]{1,64}$')


def validate_worktree_name(name: str) -> str | None:
    if not name:
        return "Worktree name cannot be empty"
    if not VALID_WT_NAME.match(name):
        return f"Invalid name '{name}': only letters, digits, dots, dashes, underscores (1-64 chars)"
    return None


def run_git(args: list[str], cwd: Path | None = None) -> tuple[bool, str]:
    try:
        r = subprocess.run(["git"] + args, cwd=cwd or WORKDIR,
                           capture_output=True, text=True, timeout=30)
        out = (r.stdout + r.stderr).strip()[:5000]
        return r.returncode == 0, out or "(no output)"
    except subprocess.TimeoutExpired:
        return False, "Error: git timeout"
    except FileNotFoundError:
        return False, "Error: git not found"
    

def log_event(event_type: str, worktree_name: str, task_id: str = ""):
    event = {"type": event_type, "worktree": worktree_name,
             "task_id": task_id, "ts": time.time()}
    events_file = WORKTREES_DIR / "events.jsonl"
    with open(events_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def create_worktree(name: str, task_id: str = "") -> str:
    err = validate_worktree_name(name)
    if err:
        return f"Error: {err}"
    path = WORKTREES_DIR / name
    if path.exists():
        return f"Worktree '{name}' already exists"
    ok, result = run_git(["worktree", "add", str(path), "-b", f"wt/{name}", "HEAD"])
    if not ok:
        return f"Git error: {result}"
    if task_id:
        from task.task_manager import load_task, save_task
        task = load_task(task_id)
        task.worktree = name
        save_task(task)
        print(f"  \033[33m[bind] {task.subject} → worktree:{name}\033[0m")
    log_event("create", name, task_id)
    print(f"  \033[33m[worktree] created: {name}\033[0m")
    return f"Worktree '{name}' created at {path}"


def remove_worktree(name: str, discard_changes: bool = False) -> str:
    err = validate_worktree_name(name)
    if err:
        return err
    path = WORKTREES_DIR / name
    if not path.exists():
        return f"Worktree '{name}' not found"
    if not discard_changes:
        ok, out = run_git(["status", "--porcelain"], cwd=path)
        files = len([l for l in out.splitlines() if l.strip()]) if ok else -1
        if files > 0:
            return (f"Worktree '{name}' has {files} uncommitted file(s). "
                    "Use discard_changes=true to force.")
    run_git(["worktree", "remove", str(path), "--force"])
    run_git(["branch", "-D", f"wt/{name}"])
    log_event("remove", name)
    print(f"  \033[33m[worktree] removed: {name}\033[0m")
    return f"Worktree '{name}' removed"


def keep_worktree(name: str) -> str:
    err = validate_worktree_name(name)
    if err:
        return err
    log_event("keep", name)
    print(f"  \033[36m[worktree] kept: {name} (branch: wt/{name})\033[0m")
    return f"Worktree '{name}' kept (branch: wt/{name})"


def get_worktree_path(name: str) -> Path | None:
    path = WORKTREES_DIR / name
    return path if path.exists() else None