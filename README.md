# PistonCore v2

**The real webCoRE editor, for Home Assistant.**

PistonCore lets Home Assistant users build automations in the genuine webCoRE visual
editor — the same dashboard thousands of SmartThings and Hubitat users have relied on for
years — and compiles the resulting pistons into native Home Assistant automations (YAML)
or PyScript for complex logic. There is no webCoRE engine running anywhere: the editor
authors standard webCoRE piston JSON, and PistonCore's compiler turns it into things Home
Assistant executes natively.

> **Status: early development — not ready for users.** The editor works against live HA
> devices and pistons save, but the compiler does not exist yet. Nothing here runs your
> automations today. Watch/star if you're interested; don't install expecting a product.

## How it works

- The **stock webCoRE dashboard** (vendored under `vendor/webcore-dashboard/`, unmodified
  except for a short, documented list of neutralizations) is served locally by a Python
  **FastAPI shim**.
- The shim **impersonates the webCoRE SmartApp API** (~25 endpoints), fabricating
  webCoRE-shaped data from Home Assistant: your HA devices appear in the editor grouped
  the way physical devices are (one picker item per device, like Hubitat), with their
  attributes, commands, and live values.
- Saved pistons are **byte-standard webCoRE piston JSON** — the format is documented in
  [PISTON_JSON_REFERENCE.md](PISTON_JSON_REFERENCE.md), which also serves as the target
  format for AI-generated and shared pistons (import/export is plain copy/paste JSON; no
  cloud, no accounts).
- The **compiler** (in progress) translates piston JSON into native HA automations where
  possible and PyScript where webCoRE semantics demand it.

## Project documents

| Doc | What it is |
|---|---|
| [SHIM_API_SPEC.md](SHIM_API_SPEC.md) | The webCoRE SmartApp API contract the shim implements |
| [DEVICE_PAYLOAD_SPEC.md](DEVICE_PAYLOAD_SPEC.md) | How HA entities become webCoRE devices (grouping, capabilities, resolution) |
| [PISTON_JSON_REFERENCE.md](PISTON_JSON_REFERENCE.md) | The webCoRE piston JSON format — compiler input, import format, AI-authoring target |
| [TRACE_ACTIVITY_CONTRACT.md](TRACE_ACTIVITY_CONTRACT.md) | The trace/console data contract (future instrumentation) |
| [COMPILER_DECISIONS_HOLDING.md](COMPILER_DECISIONS_HOLDING.md) | Compiler decisions held until the compiler spec exists |
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
