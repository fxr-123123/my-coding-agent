from tools.base_tool import BaseTool
from tools.tool_registry import registry
from task.cron_scheduler import schedule_job, cancel_job, scheduled_jobs, cron_lock


class ScheduleCronTool(BaseTool):
    name = "schedule_cron"
    description = "注册一个 cron 定时任务。cron 格式：分 时 日 月 周（5段）。"
    input_schema = {
        "type": "object",
        "properties": {
            "cron": {"type": "string", "description": "5段 cron 表达式，如 0 9 * * *"},
            "prompt": {"type": "string", "description": "触发时注入的消息"},
            "recurring": {"type": "boolean", "description": "是否重复，默认 true"},
            "durable": {"type": "boolean", "description": "是否持久化，默认 true"},
        },
        "required": ["cron", "prompt"],
    }

    def run(self, cron: str, prompt: str, recurring: bool = True,
            durable: bool = True) -> str:
        result = schedule_job(cron, prompt, recurring, durable)
        if isinstance(result, str):
            return result
        return f"Scheduled {result.id}: '{cron}' → {prompt}"


class ListCronsTool(BaseTool):
    name = "list_crons"
    description = "列出所有已注册的 cron 定时任务"
    input_schema = {"type": "object", "properties": {}, "required": []}

    def run(self) -> str:
        with cron_lock:
            jobs = list(scheduled_jobs.values())
        if not jobs:
            return "No cron jobs."
        lines = []
        for j in jobs:
            tag = "recurring" if j.recurring else "one-shot"
            dur = "durable" if j.durable else "session"
            lines.append(
                f"  {j.id}: '{j.cron}' → {j.prompt[:50]} [{tag}, {dur}]"
            )
        return "\n".join(lines)


class CancelCronTool(BaseTool):
    name = "cancel_cron"
    description = "根据 ID 取消定时任务"
    input_schema = {
        "type": "object",
        "properties": {"job_id": {"type": "string"}},
        "required": ["job_id"],
    }

    def run(self, job_id: str) -> str:
        return cancel_job(job_id)
    

registry.register(ScheduleCronTool)
registry.register(ListCronsTool)
registry.register(CancelCronTool)