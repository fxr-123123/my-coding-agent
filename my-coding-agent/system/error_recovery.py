import time
import random

DEFAULT_MAX_TOKENS = 8000
ESCALATED_MAX_TOKENS = 64000
MAX_RECOVERY_RETRIES = 3       # continuation 最大次数
MAX_RETRIES = 10               # 429/529 重试上限
BASE_DELAY_MS = 500            # 退避基数
MAX_CONSECUTIVE_529 = 3        # 连续 529 后切换模型

CONTINUATION_PROMPT = (
    "Output token limit hit. Resume directly — "
    "no apology, no recap. Pick up mid-thought."
)


# ── 恢复状态 ──

class RecoveryState:
    def __init__(self):
        self.has_escalated = False
        self.recovery_count = 0
        self.consecutive_529 = 0
        self.has_attempted_reactive_compact = False


# ── 退避延迟 ──

def retry_delay(attempt: int, retry_after: float | None = None) -> float:
    """指数退避 + 随机抖动。Retry-After 优先级最高。"""
    if retry_after:
        return retry_after
    base = min(BASE_DELAY_MS * (2 ** attempt), 32000) / 1000
    jitter = random.uniform(0, base * 0.25)
    return base + jitter


# ── 重试包装 ──

def with_retry(fn, state: RecoveryState, model_callback=None):
    """429/529 时指数退避重试，529 连续失败切换模型"""
    for attempt in range(MAX_RETRIES):
        try:
            result = fn()
            state.consecutive_529 = 0
            return result
        except Exception as e:
            name = type(e).__name__.lower()
            msg = str(e).lower()

            # 429 rate limit
            if "ratelimit" in name or "429" in msg:
                delay = retry_delay(attempt)
                print(f"  \033[33m[429] retry {attempt+1}/{MAX_RETRIES}, "
                      f"wait {delay:.1f}s\033[0m")
                time.sleep(delay)
                continue

            # 529 overloaded
            if "overloaded" in name or "529" in msg or "overloaded" in msg:
                state.consecutive_529 += 1
                if state.consecutive_529 >= MAX_CONSECUTIVE_529 and model_callback:
                    model_callback()
                    state.consecutive_529 = 0
                    print(f"  \033[31m[529×{MAX_CONSECUTIVE_529}] switching model\033[0m")
                delay = retry_delay(attempt)
                print(f"  \033[33m[529] retry {attempt+1}/{MAX_RETRIES}, "
                      f"wait {delay:.1f}s\033[0m")
                time.sleep(delay)
                continue

            raise  # 非瞬态错误，外抛
    raise RuntimeError(f"Max retries ({MAX_RETRIES}) exceeded")


# ── prompt_too_long 检测 ──

def is_prompt_too_long_error(e: Exception) -> bool:
    msg = str(e).lower()
    return (("prompt" in msg and "long" in msg)
            or "prompt_is_too_long" in msg
            or "context_length_exceeded" in msg
            or "too many tokens" in msg)