"""Load and validate a skill's eval config (prompts.yaml + process-checks.json)."""
from __future__ import annotations
import json
from pathlib import Path

import yaml
from pydantic import BaseModel

from evals.lib.models import PromptConfig

EVALS_DIR = Path(__file__).resolve().parent.parent  # repo/evals


class SkillConfig(BaseModel):
    skill: str
    prompts: list[PromptConfig]
    checks: list[dict]


def load_skill(skill: str, base_dir: Path | None = None) -> SkillConfig:
    base = base_dir or EVALS_DIR
    skill_dir = base / skill
    prompts_raw = yaml.safe_load((skill_dir / "prompts.yaml").read_text()) or []
    prompts = [PromptConfig(**row) for row in prompts_raw]  # raises on bad fields

    ids = [p.id for p in prompts]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate prompt id(s) in {skill}: {sorted(dupes)}")

    checks = json.loads((skill_dir / "process-checks.json").read_text())["checks"]
    id_set = set(ids)
    for c in checks:
        for target in c.get("applies_to", []):
            if target not in id_set:
                raise ValueError(
                    f"check '{c['id']}' applies_to references unknown prompt '{target}'")

    return SkillConfig(skill=skill, prompts=prompts, checks=checks)
