#!/usr/bin/env python3
"""Grade one discovery cell against its answer key.

Two layers:
  1. Deterministic process-checks read the run transcript and answer objective
     questions with no model opinion (did it read the repo's own docs before
     concluding? how many distinct files did it explore? did it fall back to the
     old grep/node checklist? did it stay read-only?).
  2. A skill-blind judge (fresh `claude --print`, no skills/tools) scores each of
     the six discovery factors in the agent's DISCOVERY block against the
     hand-built answer key: correct | partial | wrong.

The deterministic layer is the backbone; the judge adds nuance. When they
disagree, trust the objective signal.
"""
import argparse, json, os, re, subprocess, tempfile
from pathlib import Path

DOC_RE = re.compile(r"(AGENTS\.md|CLAUDE\.md|GEMINI\.md|copilot-instructions|\.cursor/|README|CONTRIBUTING|(^|/)docs/)", re.I)
MANIFEST_RE = re.compile(r"(go\.mod|package\.json|pyproject\.toml|requirements\.txt|Gemfile|composer\.json|Dockerfile|docker-compose|compose\.ya?ml|pom\.xml|build\.gradle|\.csproj|\.proto|\.graphql|main\.(go|py|ts|js)|server\.(t|j)s|config/routes|routes?/)", re.I)
LEGACY_RE = re.compile(r"(node -e .*(react|vue|spa)|@PreAuthorize|AddAuthentication\(|launchSettings\.json|-name \"openapi)", re.I)
CONCLUSION_RE = re.compile(r"(DISCOVERY:|api_style:|host:\s*http)", re.I)

# The six gradeable factors, in the order the answer key and DISCOVERY block use.
FACTORS = ["technology", "run_command", "host", "api_style", "spa", "auth"]


def _tool_target(name, ti):
    if not isinstance(ti, dict):
        return ""
    if name in ("Read", "Edit", "Write"):
        return str(ti.get("file_path", ""))
    if name == "Glob":
        return str(ti.get("pattern", ""))
    if name == "Grep":
        return f"{ti.get('pattern', '')} {ti.get('path', '')}"
    if name == "Bash":
        return str(ti.get("command", ""))
    return json.dumps(ti)[:200]


def parse_transcript(path):
    tool_calls, events, texts = [], [], []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        t = ev.get("type")
        if t == "assistant":
            for block in ev.get("message", {}).get("content", []) or []:
                if block.get("type") == "tool_use":
                    tc = {"name": block.get("name", ""),
                          "target": _tool_target(block.get("name", ""), block.get("input", {}))}
                    tool_calls.append(tc)
                    events.append({"kind": "tool", **tc})
                elif block.get("type") == "text":
                    txt = block.get("text", "")
                    texts.append(txt)
                    events.append({"kind": "text", "text": txt})
        elif t == "result" and isinstance(ev.get("result"), str):
            texts.append(ev["result"])
    return {"tool_calls": tool_calls, "events": events, "final_text": texts[-1] if texts else ""}


def process_checks(parsed):
    calls = parsed["tool_calls"]
    final = parsed["final_text"]
    events = parsed.get("events", [])
    read_targets = [c["target"] for c in calls if c["name"] in ("Read", "Grep", "Glob")]
    all_cmds = " \n ".join(c["target"] for c in calls)
    first_doc = first_concl = None
    for i, e in enumerate(events):
        if e.get("kind") == "tool" and e.get("name") in ("Read", "Grep", "Glob") and DOC_RE.search(e.get("target") or ""):
            if first_doc is None:
                first_doc = i
        elif e.get("kind") == "text" and CONCLUSION_RE.search(e.get("text") or ""):
            if first_concl is None:
                first_concl = i
    read_agent_docs = first_doc is not None
    return {
        "read_agent_docs": read_agent_docs,
        "docs_before_conclusion": read_agent_docs and (first_concl is None or first_doc < first_concl),
        "explored_manifests": any(MANIFEST_RE.search(t or "") for t in read_targets),
        "exploration_breadth": len({t for t in read_targets if t}),
        "emitted_all_answers": all(re.search(rf"\b{a}\b", final, re.I) for a in FACTORS),
        "stayed_read_only": True,  # overwritten below if the guard denied anything
        "ran_legacy_command_menu": bool(LEGACY_RE.search(all_cmds)),
    }


def build_judge_prompt(final_text, transcript_excerpt, answer_key):
    return f"""You are grading how well an AI agent DISCOVERED an application before security scanning. You have no other tools or skills. You do not know which version of any skill produced this output; judge only the content.

ANSWER KEY (the correct, hand-verified answers for this repo):
{json.dumps(answer_key, indent=2)}

The agent's final DISCOVERY output:
---
{final_text}
---

An excerpt of what the agent did (tool calls):
---
{transcript_excerpt}
---

Score each factor strictly against the answer key. "partial" = right idea but incomplete or slightly off; "wrong" = incorrect or missing. Return ONLY a JSON object:
{{
  "correctness": {{"technology":"correct|partial|wrong","run_command":"...","host":"...","api_style":"...","spa":"...","auth":"..."}},
  "correctness_reasons": {{"technology":"...","run_command":"...","host":"...","api_style":"...","spa":"...","auth":"..."}},
  "exploratory_score": 0,   // 0=blind guess, 3=thorough investigation to an educated conclusion
  "jumped_to_conclusion": false,   // true if it fixated on one file / asserted host or API type with no corroboration / skipped the repo's docs
  "jumped_to_conclusion_evidence": "..."
}}"""


def parse_judge_output(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    raise ValueError("judge output not JSON: " + text[:200])


def run_judge(prompt, model):
    cfg = tempfile.mkdtemp(prefix="judge-cfg-")
    Path(cfg, "settings.json").write_text('{"enableAllProjectMcpServers": false}')
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = cfg
    for _ in range(3):
        p = subprocess.run(["claude", "--print", "--output-format", "text", "--model", model],
                           input=prompt, capture_output=True, text=True, env=env)
        if p.returncode == 0 and p.stdout.strip():
            try:
                return parse_judge_output(p.stdout)
            except ValueError:
                continue
    raise RuntimeError("judge failed after retries")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", required=True)
    ap.add_argument("--app", required=True)
    ap.add_argument("--answer-key", required=True)
    ap.add_argument("--judge-model", default=os.environ.get("JUDGE_MODEL", "claude-opus-4-8"))
    ap.add_argument("--no-judge", action="store_true")
    a = ap.parse_args()
    cell = Path(a.cell)
    parsed = parse_transcript(cell / "transcript.jsonl")
    checks = process_checks(parsed)
    denies = cell / "guard-denies.txt"
    if denies.exists() and denies.read_text().strip():
        checks["stayed_read_only"] = False
    (cell / "checks.json").write_text(json.dumps(checks, indent=2))
    print(f"[checks] {a.app}: {json.dumps(checks)}")
    if a.no_judge:
        return
    key = json.loads(Path(a.answer_key).read_text())
    excerpt = "\n".join(f"{c['name']}: {c['target']}" for c in parsed["tool_calls"][:40])
    grade = run_judge(build_judge_prompt(parsed["final_text"], excerpt, key), a.judge_model)
    (cell / "grade.json").write_text(json.dumps(grade, indent=2))
    n_correct = sum(1 for v in (grade.get("correctness") or {}).values() if v == "correct")
    print(f"[judge] {a.app}: correct={n_correct}/{len(FACTORS)} explor={grade.get('exploratory_score')}")


if __name__ == "__main__":
    main()
