# PistonCore v2

**The real webCoRE editor, for Home Assistant.**

PistonCore lets Home Assistant users build automations in the genuine webCoRE visual
editor — the same dashboard thousands of SmartThings and Hubitat users have relied on for
years — and compiles the resulting pistons into native Home Assistant automations (YAML)
or PyScript for complex logic. There is no webCoRE engine running anywhere: the editor
authors standard webCoRE piston JSON, and PistonCore's compiler turns it into things Home
Assistant executes natively.

**PistonCore is not a home automation platform. It is a tool for building automations on
top of one.** It reads what HA already has, gives you the best visual editor ever made
for writing logic against it, and compiles that logic to native HA files.

**Your automations are yours.** Compiled pistons are standard HA files. Uninstall
PistonCore tomorrow and every simple piston keeps running natively; complex pistons keep
running as long as PyScript remains installed. No lock-in, no cloud, no account, nothing
phoning home.

> **Status: early alpha — looking for testers (Docker only).**  
> For people who know webCoRE and Docker. The editor, save path, and dual-band compiler
> (YAML-first + PyScript fallback) are built, and the compiler produces native HA files
> for real pistons — but **very little of that output has been verified running on live
> HA yet. Compiling is not the same as tested: treat everything the compiler emits as
> unverified until you've watched it run.** First-run wizard and Samba write path work.
> Test devices (for behavioral testing) and the trace/activity console are in development —
> spec'd, not built yet. There is no HA add-on — Docker only. **Port from webCoRE:** bin
> codes work *into* PistonCore; export out is plain piston JSON (not bins). JSON paste also
> works both ways. Bring real pistons and real devices — report where compile or behavior
> is wrong, **and** where the editor is missing capabilities or devices don't show up right
> (research-backed mapping, not every device type has been live-checked). **Don't put the
> house on it — assume a piston is broken until you've verified it yourself.** Expect rough
> edges. This is under active development; watch the repo and check back for updates. Alpha
> feedback is the fastest way to widen compiler and editor coverage.

## How it works

- The **stock webCoRE dashboard** (vendored under `dashboard/`, unmodified except for a
  short, documented list of neutralizations) is served locally by a Python **FastAPI shim**.
- The shim **impersonates the webCoRE SmartApp API** (~25 endpoints), fabricating
  webCoRE-shaped data from Home Assistant: your HA devices appear in the editor grouped
  the way physical devices are (one picker item per device, like Hubitat), with their
  attributes, commands, and live values.
- Saved pistons are **byte-standard webCoRE piston JSON** — the same internal format the
  real engine stores. **Import from webCoRE:** bin codes work *in*; you can also paste
  piston JSON. **Export from PistonCore:** plain JSON copy/paste only (no bin codes out,
  no accounts, no cloud). That JSON is what the compiler treats as law — and what you
  share without a sensitive full backup. Details:
  [PISTON_JSON_REFERENCE.md](PISTON_JSON_REFERENCE.md). Also the target for AI-authored
  pistons.
- The **compiler** translates piston JSON into native HA automations where possible and
  PyScript where webCoRE semantics demand it. YAML is the default path; PyScript is the
  routed exception (`routing_table.json`). Simple pistons become a standard YAML
  automation/script pair with zero external dependencies. Complex features HA YAML can't
  express fall through to PyScript. Compile runs automatically on save. Compiler behavior
  is driven by editable Jinja2 templates and JSON maps on the `/data` volume, not
  hardcoded Python. (Producing that output is well exercised against a real-piston corpus;
  verifying it *runs correctly* on live HA is the part that's still thin — see status.)

## Install (early alpha — Docker only)

Assumes you already know how to build and run a Docker container and how to give it a
persistent volume. There is no published image or HA add-on yet; you build from source.

```bash
git clone https://github.com/jercoates/pistoncore-v2.git
cd pistoncore-v2
docker build -t pistoncore-v2 .
docker run -d --name pistoncore-v2 \
  -p 7777:7777 \
  -v /path/to/pistoncore-data:/data \
  --restart unless-stopped \
  pistoncore-v2
```

Open `http://<host>:7777`. The **first-run wizard** walks you through:

1. **HA connection** — URL + long-lived access token
2. **Write target** — how compiled automations reach HA's `/config`:
   - **Local path** — bind-mount HA's config into the container (or a host mount of a
     Samba share), set `ha_config_path`
   - **In-app SMB** — PistonCore connects to HA's Samba share add-on directly (host,
     share, credentials). Tested and working.

Use the wizard's "Test write target" before finishing. After that you're on the front
door; create or import a piston and it compiles on save.

An HA add-on path is planned later (same image, supervisor auth). For now this is
Docker-only on purpose — alpha testers are expected to be comfortable there.

## Project documents

| Doc | What it is |
|---|---|
| [SHIM_API_SPEC.md](SHIM_API_SPEC.md) | The webCoRE SmartApp API contract the shim implements |
| [DEVICE_PAYLOAD_SPEC.md](DEVICE_PAYLOAD_SPEC.md) | How HA entities become webCoRE devices (grouping, capabilities, resolution) |
| [PISTON_JSON_REFERENCE.md](PISTON_JSON_REFERENCE.md) | The webCoRE piston JSON format — compiler input, import format, AI-authoring target |
| [COMPILER_SPEC.md](COMPILER_SPEC.md) | Compiler pipeline, routing, emission rules, and non-negotiable policy |
| [COMPILER_DECISIONS_DEPLOY.md](COMPILER_DECISIONS_DEPLOY.md) | Deploy layout, write transport, pause/resume, check_config, recompile-all |
| [RECONCILIATION.md](RECONCILIATION.md) | Load-bearing decisions checked against current code |
| [TRACE_ACTIVITY_CONTRACT.md](TRACE_ACTIVITY_CONTRACT.md) | The trace/console data contract (in development) |
| [VIRTUAL_DEVICES_SPEC.md](VIRTUAL_DEVICES_SPEC.md) | Test devices for behavioral testing (spec'd — in development) |
| [CLAUDE.md](CLAUDE.md) | Working rules for AI-assisted development sessions |

## Relationship to webCoRE

This project vendors and serves the webCoRE dashboard, © 2016 Adrian Caramaliu, GPL-3.0,
from [ady624/webCoRE](https://github.com/ady624/webCoRE) (with reference to the Hubitat
fork, [imnotbob/webCoRE](https://github.com/imnotbob/webCoRE)). PistonCore is an
independent project — **not affiliated with or endorsed by the webCoRE authors or
maintainers**. Please don't report PistonCore issues to them. Enormous respect and thanks
to ady624, imnotbob/E_Sch, ipaterson, and the webCoRE community for eight-plus years of
the best visual automation editor in home automation.

PistonCore v1 (a from-scratch wizard editor targeting the same goal) lives at
[jercoates/pistoncore](https://github.com/jercoates/pistoncore) and is retired in favor
of this approach.

## License

GPL-3.0 — required by, and gratefully inherited from, the vendored webCoRE dashboard.
See [LICENSE](LICENSE).
