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

For people comfortable building and running a Docker container with a persistent volume.
There's no published image or HA add-on yet — you build from source.

**Pick a deliberate, persistent location first** — don't run this from `/`, your home root,
or a temp dir, or the source ends up somewhere you didn't mean (on **Unraid** especially,
never clone to the array root — use `appdata`). Keep the **source** and PistonCore's
**data** in two separate folders.

```bash
# generic example — substitute your own persistent paths
SRC=/opt/pistoncore-v2-src           # Unraid: /mnt/user/appdata/pistoncore-v2-src
DATA=/opt/pistoncore-v2-data         # Unraid: /mnt/user/appdata/pistoncore-v2-data
mkdir -p "$SRC" "$DATA"

git clone https://github.com/jercoates/pistoncore-v2.git "$SRC"
cd "$SRC"
docker build -t pistoncore-v2 .
docker run -d --name pistoncore-v2 \
  -p 7777:7777 \
  -v "$DATA":/data \
  --restart unless-stopped \
  pistoncore-v2
```

**Updating later** (this is where people trip up): the container keeps running old code
until you rebuild *and* recreate it — a `docker restart` does nothing.
```bash
cd "$SRC" && git pull          # must say "Fast-forward"; check: git log --oneline -1
docker build -t pistoncore-v2 .
docker rm -f pistoncore-v2     # remove the old container...
docker run -d ...              # ...then re-run with the same flags as above
```

Open `http://<host>:7777` and the **first-run wizard** walks you through three things:

1. **Connect to Home Assistant** — your HA URL and a **long-lived access token**. Get the
   token in HA: your profile → **Security** → **Long-Lived Access Tokens** → **Create
   Token**.
2. **Choose where PistonCore writes** — how compiled automations reach HA's config folder.
   Pick the one that matches how you run Home Assistant:
   - **HA in Docker → bind-mount (local path).** A Docker HA has no add-ons, so there's no
     Samba share to use. Instead, mount HA's config folder into the PistonCore container
     and point the wizard at it: add a second volume to the `docker run` above, e.g.
     `-v /path/to/homeassistant/config:/ha-config`, and set the config path to
     `/ha-config`. *(Verified against a fresh Docker HA: PistonCore writes in this way,
     backs up `configuration.yaml` first, and HA still reports its config valid.)*
   - **HA OS / Supervised → in-app SMB.** If you run Home Assistant OS or Supervised,
     install the **Samba share** add-on and give PistonCore its host / share / credentials
     in the wizard — no bind-mount needed. *(This is the path developed and tested on the
     author's own setup.)*
3. **Let HA load the files** — the wizard shows the **exact `configuration.yaml` lines** it
   will add (after taking a timestamped backup), then applies them and reloads HA.

Use the wizard's **Test write access** before finishing. After that you're on the front
door — create or import a piston and it compiles on save.

**PyScript is optional.** Simple pistons run as plain HA automations with nothing extra.
Pistons that use formulas, loops, variables, event blocks, or computed messages need
PyScript — install it any time from HACS (search "pyscript"); nothing breaks without it.

An HA add-on path (sidebar entry, automatic auth) is planned later. For now it's
Docker-only on purpose — alpha testers are expected to be comfortable there.

## Will this break my Home Assistant?

It's built hard not to, and the one risky step is gated behind your explicit approval.

- **It only *adds* its own files.** Compiled pistons go into PistonCore's own folders
  (`pistoncore/automations/`, `pistoncore/scripts/`). Your existing automations, scripts,
  and entities are left alone.
- **It never edits `configuration.yaml` without showing you first.** The one file it has
  to change gets a **timestamped backup written first**, and the wizard shows you the
  **exact lines** it will add *before* it writes anything — you approve, then it applies.
- **It checks the result.** Before a deploy goes live, PistonCore runs Home Assistant's
  own configuration check; a failed check **stops the deploy** instead of shipping a broken
  file. *(Verified: after PistonCore's edits, a fresh Docker HA reported its config valid.)*
- **No lock-in.** Compiled pistons are ordinary HA files. Remove PistonCore and your simple
  automations keep running natively; complex ones keep running as long as PyScript is
  installed.

Still — this is alpha (see the status note up top), so keep your own backups as you would
for any change. PistonCore is designed to add-and-back-up, not overwrite, but don't skip
your own safety net yet.

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
