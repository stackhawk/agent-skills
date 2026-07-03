#!/usr/bin/env python3
"""PreToolUse guardrail: discovery is read-only. Exit 0 allow, 2 deny (reason on stderr)."""
import json, re, sys

def deny(msg):
    sys.stderr.write(f"Denied (read-only discovery): {msg}\n")
    sys.exit(2)

def main():
    try:
        event = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # unparseable -> don't block
    tool = event.get("tool_name", "")
    ti = event.get("tool_input", {}) or {}

    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        deny(f"{tool} would modify files")

    if tool == "Bash":
        cmd = ti.get("command", "") or ""
        low = cmd.lower()
        if re.search(r"\bhawk\s+scan\b", low):
            deny("hawk scan is out of scope for discovery")
        if re.search(r"\bgit\s+(commit|push)\b", low):
            deny("git commit/push not allowed")
        if re.search(r"\b(docker|docker-compose|podman|nerdctl)\b", low) \
           or re.search(r"\b(npm|pnpm|yarn)\s+(start|run\s+dev|run\s+serve|serve)\b", low) \
           or re.search(r"\b(bootrun|runserver|uvicorn|gunicorn|hypercorn|nodemon)\b", low) \
           or re.search(r"spring-boot:run|flask\s+run|mix\s+phx\.server|air\b|./gradlew\s+bootrun", low):
            deny("starting the app/server/container is out of scope for read-only discovery")
        if re.search(r"\b(rm|mv|tee|dd)\b|>\s*\S|>>", cmd):
            deny("file mutation not allowed")
        classic_net_tools = r"\b(curl|wget|nc|ncat|telnet|ssh|scp)\b"
        interpreter_tools = r"\b(python3?|node|nodejs|ruby|perl|php|pip3?|npm|npx|gem)\b"
        if re.search(classic_net_tools, low):
            # These tools take hosts directly, so the broad heuristic (URL,
            # generic dotted-hostname, or bare IPv4) is appropriate.
            hosts = re.findall(r"https?://([^/\s:]+)|(?:^|\s)([a-z0-9.-]+\.[a-z]{2,})", low)
            flat = [h for pair in hosts for h in pair if h]
            flat += re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", low)
            local = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
            if any(h not in local and not h.startswith("127.") for h in flat):
                deny(f"network egress to non-local host: {flat}")
        elif re.search(interpreter_tools, low):
            # These tools routinely take filename args (manage.py, index.js,
            # requirements.txt), so only match explicit URLs and bare IPv4
            # literals -- never the generic word.ext hostname regex.
            flat = re.findall(r"https?://([^/\s:]+)", low)
            flat += re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", low)
            local = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
            if any(h not in local and not h.startswith("127.") for h in flat):
                deny(f"network egress to non-local host: {flat}")
    sys.exit(0)

if __name__ == "__main__":
    main()
