# tests/lib/test_config.py
import json
import textwrap
import pytest
from pydantic import ValidationError
from evals.lib.config import load_skill, SkillConfig


def _write_skill(tmp_path, prompts_yaml: str, checks: dict):
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    (skill_dir / "prompts.yaml").write_text(prompts_yaml)
    (skill_dir / "process-checks.json").write_text(json.dumps(checks))
    return skill_dir


def test_load_skill_parses_prompts_and_checks(tmp_path):
    yaml_text = textwrap.dedent("""
      - id: d-01
        should_trigger: true
        invocation_type: explicit
        prompt: do the thing
        budget:
          bash_commands: 5
        expected:
          - signal: "hawk scan"
    """)
    checks = {"skill": "demo", "checks": [
        {"id": "c1", "type": "command_executed", "signals": ["hawk scan"],
         "severity": "blocking"}]}
    skill_dir = _write_skill(tmp_path, yaml_text, checks)

    cfg = load_skill("demo", base_dir=skill_dir.parent)
    assert isinstance(cfg, SkillConfig)
    assert cfg.skill == "demo"
    assert len(cfg.prompts) == 1
    assert cfg.prompts[0].budget.bash_commands == 5
    assert cfg.checks[0]["id"] == "c1"


def test_load_skill_rejects_bad_prompt_field(tmp_path):
    yaml_text = textwrap.dedent("""
      - id: d-01
        should_trigger: true
        invocation_type: explicit
        prompt: x
        budget_usd: 0.1
    """)
    skill_dir = _write_skill(tmp_path, yaml_text, {"skill": "demo", "checks": []})
    with pytest.raises(ValidationError):
        load_skill("demo", base_dir=skill_dir.parent)


def test_load_skill_rejects_duplicate_ids(tmp_path):
    yaml_text = textwrap.dedent("""
      - id: dup
        should_trigger: true
        invocation_type: explicit
        prompt: a
      - id: dup
        should_trigger: false
        invocation_type: negative
        prompt: b
    """)
    skill_dir = _write_skill(tmp_path, yaml_text, {"skill": "demo", "checks": []})
    with pytest.raises(ValueError, match="duplicate prompt id"):
        load_skill("demo", base_dir=skill_dir.parent)


def test_load_skill_rejects_applies_to_unknown_prompt(tmp_path):
    yaml_text = textwrap.dedent("""
      - id: d-01
        should_trigger: true
        invocation_type: explicit
        prompt: x
    """)
    checks = {"skill": "demo", "checks": [
        {"id": "c1", "type": "command_executed", "signals": ["x"],
         "severity": "warning", "applies_to": ["nope"]}]}
    skill_dir = _write_skill(tmp_path, yaml_text, checks)
    with pytest.raises(ValueError, match="applies_to references unknown prompt"):
        load_skill("demo", base_dir=skill_dir.parent)
