import json
import time
import random
import threading
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict

WORKDIR = Path.cwd()
DURABLE_PATH = WORKDIR / ".scheduled_tasks.json"

@dataclass
class CronJob:
    id: str
    cron: str        # "0 9 * * *"
    prompt: str
    recurring: bool
    durable: bool


scheduled_jobs: dict[str, CronJob] = {}
cron_queue: list[CronJob] = []
cron_lock = threading.Lock()
_last_fired: dict[str, str] = {}


# ── Cron 表达式匹配 ──

def _cron_field_matches(field: str, value: int) -> bool:
    if field == "*":
        return True
    if field.startswith("*/"):
        step = int(field[2:])
        return step > 0 and value % step == 0
    if "," in field:
        return any(_cron_field_matches(f.strip(), value)
                   for f in field.split(","))
    if "-" in field:
        lo, hi = field.split("-", 1)
        return int(lo) <= value <= int(hi)
    return value == int(field)


def cron_matches(cron_expr: str, dt: datetime) -> bool:
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        return False
    minute, hour, dom, month, dow = fields
    dow_val = (dt.weekday() + 1) % 7  # Python Mon=0 → cron Sun=0
    m = _cron_field_matches(minute, dt.minute)
    h = _cron_field_matches(hour, dt.hour)
    dom_ok = _cron_field_matches(dom, dt.day)
    month_ok = _cron_field_matches(month, dt.month)
    dow_ok = _cron_field_matches(dow, dow_val)
    if not (m and h and month_ok):
        return False
    dom_free = dom == "*"
    dow_free = dow == "*"
    if dom_free and dow_free:
        return True
    if dom_free:
        return dow_ok
    if dow_free:
        return dom_ok
    return dom_ok or dow_ok


# ── 校验 ──

def _validate_cron_field(field: str, lo: int, hi: int) -> str | None:
    if field == "*":
        return None
    if field.startswith("*/"):
        step = int(field[2:]) if field[2:].isdigit() else 0
        if step <= 0:
            return f"Invalid step: {field}"
        return None
    if "," in field:
        for part in field.split(","):
            err = _validate_cron_field(part.strip(), lo, hi)
            if err:
                return err
        return None
    if "-" in field:
        a, b = field.split("-", 1)
        if not a.isdigit() or not b.isdigit():
            return f"Invalid range: {field}"
        if int(a) < lo or int(b) > hi or int(a) > int(b):
            return f"Range {field} out of bounds"
        return None
    if not field.isdigit() or not lo <= int(field) <= hi:
        return f"Value {field} out of bounds [{lo}-{hi}]"
    return None


def validate_cron(cron_expr: str) -> str | None:
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        return f"Expected 5 fields, got {len(fields)}"
    bounds = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    names = ["minute", "hour", "day-of-month", "month", "day-of-week"]
    for i, (field, (lo, hi), name) in enumerate(zip(fields, bounds, names)):
        err = _validate_cron_field(field, lo, hi)
        if err:
            return f"{name}: {err}"
    return None


# ── 持久化 ──

def save_durable_jobs():
    durable_list = [asdict(j) for j in scheduled_jobs.values() if j.durable]
    DURABLE_PATH.write_text(json.dumps(durable_list, indent=2, ensure_ascii=False))

def load_durable_jobs():
    if not DURABLE_PATH.exists():
        return
    try:
        jobs = json.loads(DURABLE_PATH.read_text())
        for j in jobs:
            job = CronJob(**j)
            if validate_cron(job.cron):
                continue
            scheduled_jobs[job.id] = job
        if jobs:
            print(f"  \033[35m[cron] loaded {len(jobs)} durable job(s)\033[0m")
    except Exception:
        pass


# ── 注册 / 取消 ──

def schedule_job(cron: str, prompt: str, recurring: bool = True,
                 durable: bool = True) -> CronJob | str:
    err = validate_cron(cron)
    if err:
        return f"Error: {err}"
    job = CronJob(
        id=f"cron_{random.randint(0, 999999):06d}",
        cron=cron, prompt=prompt,
        recurring=recurring, durable=durable,
    )
    with cron_lock:
        scheduled_jobs[job.id] = job
    if durable:
        save_durable_jobs()
    print(f"  \033[35m[cron register] {job.id} '{cron}' → {prompt[:50]}\033[0m")
    return job


def cancel_job(job_id: str) -> str:
    with cron_lock:
        job = scheduled_jobs.pop(job_id, None)
    if not job:
        return f"Job {job_id} not found"
    if job.durable:
        save_durable_jobs()
    print(f"  \033[31m[cron cancel] {job_id}\033[0m")
    return f"Cancelled {job_id}"


# ── 调度线程 ──


def cron_scheduler_loop():
    while True:
        time.sleep(1)
        now = datetime.now()
        minute_marker = now.strftime("%Y-%m-%d %H:%M")
        with cron_lock:
            for job in list(scheduled_jobs.values()):
                try:
                    if cron_matches(job.cron, now):
                        if _last_fired.get(job.id) != minute_marker:
                            cron_queue.append(job)
                            _last_fired[job.id] = minute_marker
                            print(f"  \033[35m[cron fire] {job.id} → "
                                  f"{job.prompt[:50]}\033[0m")
                            if not job.recurring:
                                scheduled_jobs.pop(job.id, None)
                                if job.durable:
                                    save_durable_jobs()
                except Exception as e:
                    print(f"  \033[31m[cron error] {job.id}: {e}\033[0m")


# ── 队列消费 ──

def consume_cron_queue() -> list[CronJob]:
    with cron_lock:
        fired = list(cron_queue)
        cron_queue.clear()
    return fired


def has_cron_queue() -> bool:
    with cron_lock:
        return bool(cron_queue)
    

# ── 启动 ──

load_durable_jobs()
threading.Thread(target=cron_scheduler_loop, daemon=True).start()
print("  \033[35m[cron] scheduler thread started\033[0m")


agent_lock = threading.Lock()

def queue_processor_loop(state_factory):
    """daemon 线程：cron 队列有积压且 agent 空闲时自动处理"""
    while True:
        time.sleep(0.5)
        if not has_cron_queue():
            continue
        if not agent_lock.acquire(blocking=False):
            continue
        try:
            if not has_cron_queue():
                continue
            print("\n  \033[35m[queue processor] delivering scheduled work\033[0m")
            state = state_factory()
            # 消费所有积压
            fired = consume_cron_queue()
            for job in fired:
                state.messages.append({
                    "role": "user",
                    "content": f"[Scheduled] {job.prompt}",
                })
                print(f"  \033[35m[inject cron] {job.prompt[:50]}\033[0m")
            # 跑 agent
            from core.agent_loop import agent_loop
            agent_loop(state)
        finally:
            agent_lock.release()
