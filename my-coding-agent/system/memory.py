import json
import os
import re
import time
from pathlib import Path

WORKDIR = Path.cwd()
MEMORY_DIR = WORKDIR / ".memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
CONSOLIDATE_THRESHOLD = 10

def _parse_frontmatter(text: str) -> tuple[dict,str]:
    """解析 YAML frontmatter，返回 (meta, body)"""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, parts[2].strip()

def _ensure_dir():
    MEMORY_DIR.mkdir(exist_ok=True)


# ── 写 ──

def write_memory(name: str, mem_type: str, description: str, body: str) -> Path:
    """写入一条记忆"""
    _ensure_dir()
    slug = name.lower().replace(" ", "-").replace("/", "-")
    filepath = MEMORY_DIR / f"{slug}.md"
    filepath.write_text(
        f"---\nname: {name}\ndescription: {description}\ntype: {mem_type}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    _rebuild_index()
    return filepath

def _rebuild_index():
    """重建 MEMORY.md 索引"""
    _ensure_dir()
    lines = []
    for f in sorted(MEMORY_DIR.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        raw = f.read_text(encoding="utf-8")
        meta, _ = _parse_frontmatter(raw)
        name = meta.get("name", f.stem)
        desc = meta.get("description", "")
        lines.append(f"- [{name}]({f.name}) — {desc}")
    MEMORY_INDEX.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")


# ── 读 ──

def read_memory_index() -> str:
    """读取索引（注入 system prompt）"""
    if not MEMORY_INDEX.exists():
        return ""
    return MEMORY_INDEX.read_text(encoding="utf-8").strip()

def list_memory_files() -> list[dict]:
    """列出所有记忆文件的元数据"""
    _ensure_dir()
    result = []
    for f in sorted(MEMORY_DIR.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        raw = f.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(raw)
        result.append({
            "filename": f.name,
            "name": meta.get("name", f.stem),
            "description": meta.get("description", ""),
            "type": meta.get("type", "user"),
            "body": body,
        })
    return result


# ── 选 ──

def select_relevant_memories(messages: list, max_items: int = 5) -> list[str]:
    """根据最近对话用 LLM 选出相关记忆"""
    files = list_memory_files()
    if not files:
        return []

    # 收集最近几轮用户文本
    recent_texts = []
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    str(getattr(b, "text", "")) for b in content
                    if getattr(b, "type", None) == "text"
                )
            if isinstance(content, str):
                recent_texts.append(content)
            if len(recent_texts) >= 3:
                break
    recent = " ".join(reversed(recent_texts))[:2000]
    if not recent.strip():
        return []

    # 构建目录给 LLM 选
    catalog = "\n".join(
        f"{i}: {f['name']} — {f['description']}"
        for i, f in enumerate(files)
    )
    prompt = (
        "Given the recent conversation and memory catalog, "
        "select indices of clearly relevant memories. "
        "Return ONLY a JSON array like [0, 3]. Return [] if none.\n\n"
        f"Recent:\n{recent}\n\nCatalog:\n{catalog}"
    )
    try:
        from anthropic import Anthropic
        client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
        response = client.messages.create(
            model=os.environ["MODEL_ID"],
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
        )
        text = ""
        for block in response.content:
            t = getattr(block, "text", None)
            if t:
                text += t
        match = re.search(r'\[.*?\]', text, re.DOTALL)
        if match:
            indices = json.loads(match.group())
            selected = []
            for idx in indices:
                if isinstance(idx, int) and 0 <= idx < len(files):
                    selected.append(files[idx]["filename"])
                    if len(selected) >= max_items:
                        break
            return selected
    except Exception:
        pass

    # 兜底：关键词匹配
    keywords = [w.lower() for w in recent.split() if len(w) > 3]
    selected = []
    for f in files:
        text = (f["name"] + " " + f["description"]).lower()
        if any(kw in text for kw in keywords):
            selected.append(f["filename"])
            if len(selected) >= max_items:
                break
    return selected

def load_memories(messages: list) -> str:
    """加载相关记忆内容，用于注入上下文"""
    selected = select_relevant_memories(messages)
    if not selected:
        return ""
    parts = ["<relevant_memories>"]
    for filename in selected:
        path = MEMORY_DIR / filename
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    parts.append("</relevant_memories>")
    return "\n\n".join(parts)


# ── 提取 ──

def extract_memories(messages: list):
    """从对话中提取新记忆"""
    dialogue_parts = []
    for msg in messages[-10:]:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                str(getattr(b, "text", "")) for b in content
                if getattr(b, "type", None) == "text"
            )
        if isinstance(content, str) and content.strip():
            dialogue_parts.append(f"{role}: {content}")
    dialogue = "\n".join(dialogue_parts)
    if not dialogue.strip():
        return

    existing = list_memory_files()
    existing_desc = "\n".join(
        f"- {m['name']}: {m['description']}" for m in existing
    ) if existing else "(none)"

    prompt = (
        "Extract user preferences, constraints, or project facts from this dialogue.\n"
        "Return JSON array. Each: {name, type, description, body}.\n"
        "type: 'user'|'feedback'|'project'|'reference'.\n"
        "If nothing new or already covered, return [].\n\n"
        f"Existing:\n{existing_desc}\n\nDialogue:\n{dialogue[:4000]}"
    )
    try:
        from anthropic import Anthropic
        client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
        response = client.messages.create(
            model=os.environ["MODEL_ID"],
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
        )
        text = ""
        for block in response.content:
            t = getattr(block, "text", None)
            if t:
                text += t
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if not match:
            return
        items = json.loads(match.group())
        if not items:
            return
        count = 0
        for mem in items:
            name = mem.get("name", f"memory_{int(time.time())}")
            mem_type = mem.get("type", "user")
            desc = mem.get("description", "")
            body = mem.get("body", "")
            if desc and body:
                write_memory(name, mem_type, desc, body)
                count += 1
        if count:
            print(f"\n\033[33m[Memory: 提取了 {count} 条新记忆]\033[0m")
    except Exception:
        pass


# ── 整理 ──

def consolidate_memories():
    """记忆超过阈值时 LLM 合并去重"""
    files = list_memory_files()
    if len(files) < CONSOLIDATE_THRESHOLD:
        return

    catalog = "\n\n".join(
        f"## {f['filename']}\nname: {f['name']}\ntype: {f['type']}\n{f['body']}"
        for f in files
    )
    prompt = (
        "Consolidate these memories. Rules:\n"
        "1. Merge duplicates\n2. Remove outdated ones\n"
        "3. Keep under 30 total\n4. Preserve user preferences\n"
        "Return JSON array: {name, type, description, body}.\n\n" + catalog[:16000]
    )
    try:
        from anthropic import Anthropic
        client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
        response = client.messages.create(
            model=os.environ["MODEL_ID"],
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
        )
        text = ""
        for block in response.content:
            t = getattr(block, "text", None)
            if t:
                text += t
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if not match:
            return
        items = json.loads(match.group())
        # 清空旧文件
        for f in MEMORY_DIR.glob("*.md"):
            if f.name != "MEMORY.md":
                f.unlink()
        for mem in items:
            name = mem.get("name", f"memory_{int(time.time())}")
            mem_type = mem.get("type", "user")
            desc = mem.get("description", "")
            body = mem.get("body", "")
            if desc and body:
                write_memory(name, mem_type, desc, body)
        print(f"\n\033[33m[Memory: 整理 {len(files)} → {len(items)} 条]\033[0m")
    except Exception:
        pass