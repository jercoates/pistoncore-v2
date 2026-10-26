#!/usr/bin/env python3
"""PistonCore rule check -- the rules that are plain facts, fed straight back
to the working chat so it corrects course in the same turn.

Two modes, chosen by the first argument:
  edit  PostToolUse on Write/Edit/Bash -- secrets, sealed dashboard, corpus
  turn  Stop (every reply)             -- code added this turn but never used

Judgement rules (hard-coded HA, duplicate tools, removed behaviour, docstrings
that contradict code) are NOT here; an agent hook handles those.

Contains no secrets: the real keys are read at runtime from the gitignored
DEV_BENCH.local.md and matched exactly.
"""
import io
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def git(*args):
    p = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, p.stdout


def ignored(rel):
    code, _ = git("check-ignore", "-q", rel)
    return code == 0


def known_secrets():
    found = set()
    try:
        text = io.open(os.path.join(REPO, "DEV_BENCH.local.md"), encoding="utf-8").read()
    except OSError:
        return found
    for m in re.finditer(r"eyJhbGciOi[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", text):
        found.add(m.group(0))
    for m in re.finditer(r"`<TOKEN>` = `([0-9a-f\-]{36})`", text):
        found.add(m.group(1))
    return found


LAN_IP = re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b")


def rel_path(path):
    if not path:
        return None
    try:
        return os.path.relpath(os.path.abspath(path), REPO).replace("\\", "/")
    except ValueError:
        return None


def read(rel):
    try:
        p = os.path.join(REPO, rel)
        if os.path.getsize(p) > 2_000_000:
            return ""
        return io.open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def check_edit(payload):
    tool = payload.get("tool_name")
    ti = payload.get("tool_input") or {}
    targets = []                                   # (rel, text added)
    if tool in ("Write", "Edit", "MultiEdit"):
        rel = rel_path(ti.get("file_path"))
        if rel and not rel.startswith(".."):
            if tool == "Write":
                added = ti.get("content") or ""
            elif tool == "Edit":
                added = ti.get("new_string") or ""
            else:
                added = "\n".join(e.get("new_string", "") for e in ti.get("edits") or [])
            targets.append((rel, added))
    elif tool == "Bash":
        # a Bash command can edit files too; check whatever is now changed
        _, out = git("status", "--porcelain", "--untracked-files=all")
        for line in out.splitlines():
            rel = line[3:].strip().strip('"')
            if " -> " in rel:
                rel = rel.split(" -> ", 1)[1]
            if rel and not rel.endswith("/"):
                targets.append((rel, read(rel)))
    problems = []
    secrets = known_secrets()
    for rel, added in targets:
        if rel.startswith("dashboard/"):
            problems.append(
                f"{rel} is under dashboard/, which is SEALED (CLAUDE.md). Nothing there "
                "may change except the enumerated neutralizations in SHIM_API_SPEC.md "
                "§9, and any other edit needs Jeremy's explicit approval first. Undo it.")
        if rel.startswith("test-pistons/") and rel.endswith(".json"):
            problems.append(
                f"{rel} is a corpus piston. The piston JSON is LAW: never edit it to "
                "make something compile or pass (HARD_RULES §13). Undo the change and "
                "find out why it failed instead.")
        if ignored(rel):
            continue                               # gitignored files may hold these
        for s in secrets:
            if s and s in added:
                problems.append(
                    f"{rel} now contains a real key or token from DEV_BENCH.local.md. "
                    "The repo is PUBLIC. Remove it and point at DEV_BENCH.local.md "
                    "instead.")
                break
        ips = sorted(set(LAN_IP.findall(added)))
        if ips:
            problems.append(
                f"{rel} now names a LAN address ({', '.join(ips)}). Machine addresses "
                "belong in the gitignored DEV_BENCH.local.md, not in a file that can "
                "reach the public repo. Replace it with a pointer.")
    return problems


DEF = re.compile(r"^\+\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)")


def check_turn(payload):
    if payload.get("stop_hook_active"):
        return []                                  # never loop on our own block
    _, diff = git("diff", "HEAD", "-U0", "--", "*.py")
    added = [l for l in diff.splitlines() if not l.startswith("+++")]
    # brand-new files are not in `git diff HEAD`, so read them whole
    _, status = git("status", "--porcelain", "--untracked-files=all")
    for line in status.splitlines():
        rel = line[3:].strip().strip('"')
        if line.startswith("??") and rel.endswith(".py") and not rel.startswith(".claude/"):
            added += ["+" + l for l in read(rel).splitlines()]
    names = set()
    for line in added:
        m = DEF.match(line)
        if m:
            n = m.group(1)
            if not (n.startswith("__") or n.startswith("test_")):
                names.add(n)
    problems = []
    for n in sorted(names):
        # --untracked so a caller sitting in a brand-new file still counts
        _, hits = git("grep", "-n", "-w", "--untracked", n, "--", "*.py")
        if len([h for h in hits.splitlines() if h.strip()]) <= 1:
            problems.append(
                f"`{n}` was added this turn and is never used anywhere. Wire it up or "
                "remove it -- dead code is not left behind in this repo.")
    return problems


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "edit"
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    problems = check_edit(payload) if mode == "edit" else check_turn(payload)
    if not problems:
        return 0
    reason = ("RULE CHECK -- fix this now, before anything else:\n- "
              + "\n- ".join(problems)
              + "\nThen tell Jeremy in one plain sentence what was caught and that "
                "it is fixed. Describe it in terms of what it means, not code.")
    out = {"decision": "block", "reason": reason,
           "systemMessage": "Rule check caught: " + problems[0][:160]}
    if mode == "edit":
        out["hookSpecificOutput"] = {"hookEventName": "PostToolUse",
                                     "additionalContext": reason}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
