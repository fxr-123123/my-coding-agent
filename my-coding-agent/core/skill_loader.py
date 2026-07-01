from pathlib import Path
import yaml

SKILLS_DIR = Path.cwd() / "skills"
SKILL_REGISTRY: dict[str, dict] = {}

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 SKILL.md 的 YAML frontmatter，返回 (meta, body)"""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, parts[2].strip()

def scan_skills():
    """启动时扫描 skills/ 目录，填充 SKILL_REGISTRY"""
    global SKILL_REGISTRY
    SKILL_REGISTRY.clear()
    if not SKILLS_DIR.exists():
        return
    for d in sorted(SKILLS_DIR.iterdir()):
        if not d.is_dir():
            continue
        manifest = d / "SKILL.md"
        if manifest.exists():
            raw = manifest.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(raw)
            name = meta.get("name", d.name)
            desc = meta.get("description", body.split("\n")[0].lstrip("#").strip())
            SKILL_REGISTRY[name] = {"name": name, "description": desc, "content": raw}

def list_skills() -> str:
    """返回技能目录摘要，注入 system prompt（Layer 1）"""
    if not SKILL_REGISTRY:
        return "(no skills fount)"
    lines = []
    for s in SKILL_REGISTRY.values():
        lines.append(f"- **{s['name']}**: {s['description']}")
    return "\n".join(lines)


def load_skill(name: str) -> str:
    """返回完整 SKILL.md 内容，通过 tool_result 注入对话（Layer 2）"""
    skill = SKILL_REGISTRY.get(name)
    if not skill:
        return f"Skill not found: {name}"
    return skill["content"]