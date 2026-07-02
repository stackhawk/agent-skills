#!/usr/bin/env python3
"""Benchmark PreToolUse guard. Always enforces eval-integrity + real-world safety.
Profile 'readonly' also blocks writes/app-starts/scans; 'sandbox-rw' allows them but
confines writes to --workdir. Exit 0 allow, exit 2 deny (reason on stderr)."""
import argparse, json, os, re, sys

EVAL_INTERNAL = re.compile(r"(ground-truth|\.superpowers|docs/superpowers|skills/benchmark/scripts|apps\.tsv|prompt\.txt)", re.I)
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
RUN_OR_SCAN = re.compile(r"\b(docker|docker-compose|podman|nerdctl)\b|\b(npm|pnpm|yarn)\s+(start|run\s+dev|run\s+serve|serve)\b|\b(bootrun|runserver|uvicorn|gunicorn|hypercorn|nodemon)\b|spring-boot:run|flask\s+run|\bhawk\s+scan\b", re.I)
WRITE_BASH = re.compile(r"\b(rm|mv|tee|dd)\b|>\s*\S|>>")

def deny(msg):
    sys.stderr.write(f"Denied (benchmark guard): {msg}\n"); sys.exit(2)

def targets(tool, ti):
    if tool in WRITE_TOOLS or tool == "Read":
        return [str(ti.get("file_path", ""))]
    if tool == "Grep": return [str(ti.get("path", "")), str(ti.get("pattern", ""))]
    if tool == "Glob": return [str(ti.get("pattern", ""))]
    if tool == "Bash": return [str(ti.get("command", ""))]
    return [json.dumps(ti)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["readonly", "sandbox-rw"], default="readonly")
    ap.add_argument("--workdir", default="")
    a = ap.parse_args()
    try:
        event = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    tool = event.get("tool_name", ""); ti = event.get("tool_input", {}) or {}
    tgts = targets(tool, ti); blob = " ".join(tgts); low = blob.lower()

    # ---- ALWAYS: eval integrity ----
    if EVAL_INTERNAL.search(blob):
        deny(f"access to eval-internal path is not allowed: {tgts}")

    # ---- ALWAYS: real-world safety ----
    if tool == "Bash":
        if re.search(r"\bgit\s+(push|remote)\b", low):
            deny("git push/remote not allowed")
        if re.search(r"\b(curl|wget|nc|ncat|telnet|ssh|scp)\b", low):
            hosts = re.findall(r"https?://([^/\s:]+)|(?:^|\s)([a-z0-9.-]+\.[a-z]{2,})", low)
            flat = [h for pair in hosts for h in pair if h]
            local = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
            if any(h not in local for h in flat):
                deny(f"network egress to non-local host: {flat}")

    if a.profile == "readonly":
        if tool in WRITE_TOOLS:
            deny(f"{tool} blocked in readonly profile")
        if tool == "Bash" and (WRITE_BASH.search(blob) or RUN_OR_SCAN.search(low)):
            deny("write/app-start/scan blocked in readonly profile")
    else:  # sandbox-rw: allow writes/runs/scans, but confine writes to workdir
        if tool in WRITE_TOOLS and a.workdir:
            fp = os.path.abspath(tgts[0]) if tgts[0] else ""
            wd = os.path.abspath(a.workdir)
            if not (fp == wd or fp.startswith(wd + os.sep)):
                deny(f"write outside workdir not allowed: {fp}")
    sys.exit(0)

if __name__ == "__main__":
    main()
