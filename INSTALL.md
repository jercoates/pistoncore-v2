# Installing PistonCore v2

**Early alpha. Docker only — there is no published image and no Home Assistant add-on.
You build from source.**

This guide covers the whole install: getting the container running, connecting it to Home
Assistant, choosing how compiled automations reach HA's config folder, and verifying the
result. Read the [status note in the README](README.md) first — the compiler produces
native HA files for real pistons, but very little of that output has been verified running
on live HA. Don't put the house on it.

---

## Before you start

You need:

- **A Docker host** — Unraid, a NAS, a Linux box, Docker Desktop. Anywhere you can run
  `docker build` and keep a container running.
- **A Home Assistant instance** the container can reach over the network.
- **Comfort with a terminal.** Alpha testers are expected to be fine here.

Two separate connections have to work, and they're configured independently:

1. **The API connection** — PistonCore talks to HA's WebSocket API to read your devices and
   to call services. This needs a URL and a long-lived token.
2. **The write target** — PistonCore writes compiled automation files into HA's `config`
   folder. HA's API can't do this, so it's a filesystem or SMB path, configured separately.

### Decide your write target first

One of the two options needs a volume flag at `docker run` time that can't be added later
without recreating the container. Decide now.

| How you run Home Assistant | Write mode | Volume flag needed? |
|---|---|---|
| **HA in Docker** (`homeassistant/home-assistant`) | **Local path (mounted folder)** — bind-mount HA's config folder | **Yes** |
| **HA OS / HA Supervised** | **SMB (Samba share)** — PistonCore connects to the Samba share add-on | No |
| **HA OS / Supervised, share already mounted on your Docker host** | **Local path (mounted folder)** — bind-mount that mount point | **Yes** |

A Docker HA has no add-ons, so there's no Samba share to point at — the bind-mount is the
path. HA OS and Supervised can go either way: let PistonCore speak SMB itself, or mount the
share at the host layer and treat it as a local path.

*(SMB is the path developed and tested on the author's own setup. The bind-mount path has
been verified against a fresh Docker HA: PistonCore writes this way, backs up
`configuration.yaml` first, and HA still reports its config valid afterward.)*

### One security note

PistonCore has no accounts and no login of its own. Anything that can reach port 7777 can
edit your automations and holds your HA token. **Keep it on your LAN or behind a VPN — do
not port-forward it to the internet.**

---

## What PistonCore writes to Home Assistant

Five places, and no sixth. Three of them are gated behind an explicit click, one is a
zero-setup default you can override or delete, and the rest is PistonCore's own folders.

**1. Its own compiled output** — `pistoncore/automations/` and `pistoncore/scripts/` under
HA's config folder. These folders belong to PistonCore. Your existing automations, scripts,
and entities are never touched. Compile runs on save; deploy is gated on HA's own
configuration check, and a failed check stops the deploy instead of shipping a broken file.

**2. The `configuration.yaml` include lines** *(shown first, applied only on your click)* —
the one file of yours it has to change. PistonCore reads it, shows you the **exact edits**
it proposes, and writes nothing until you agree. A **timestamped backup is taken first**.
You can always decline and add the two lines by hand instead — PistonCore doesn't need to be
the one that does it. Details in [Step 5](#step-5--let-ha-load-pistoncores-folders).

**3. The Location Mode helper** *(created automatically on first load)* — one `input_select`,
because webCoRE's Location Mode has no HA equivalent and the editor needs something real to
read. This one is deliberately zero-setup rather than a prompt: it's created once, remembered
in settings so a later load never makes a second one, and you can point PistonCore at your
own entity instead or delete it outright. Covered in
[Step 3](#step-3--create-a-home-assistant-long-lived-token).

**4. The test-devices integration** *(shown first, installed only on your click)* — copied
into `custom_components/` only if you choose to install it, after PistonCore shows you
exactly what it will copy. Covered under [Optional pieces](#test-devices).

**5. Helper entities for piston variables** *(shown first, applied only on your click)* —
some webCoRE variables have to survive between automations. A piston that sets a
"manually switched on" flag in one place and checks it back later is the common case: the
flag has to outlive the run that set it, and Home Assistant's own automation variables
cannot do that. PistonCore writes those variables as helpers into
`pistoncore_packages/pistoncore_variables.yaml` and reloads them — **no HA restart**.

It is a *packages* folder on purpose. A package **merges** with your configuration, so if
you already define `input_boolean:` yourself, PistonCore's helpers sit alongside yours
instead of colliding with them — a duplicate key there would stop HA from starting.

Only variables that genuinely need one get a helper. A variable used and finished inside a
single statement stays a plain automation variable and creates nothing. Each helper is named
`pistoncore_<piston>_<variable>`, so you can always tell which piston owns it, and they are
removed when the piston is deleted.

Every one of these is reversible and all five are listed in
[Removing PistonCore](#removing-pistoncore), so you can see the whole footprint in one place
and undo it item by item.

---

## Step 1 — Pick persistent locations

Pick a deliberate, persistent place for both the source and the data. Don't run this from
`/`, your home root, or a temp dir. **On Unraid, never clone to the array root — use
`appdata`.**

Keep the **source** and the **data** in two separate folders. The source is disposable and
gets replaced on every update. The data folder holds your pistons, your settings, and the
editable compiler templates and JSON maps, and must survive rebuilds.

```bash
# generic
SRC=/opt/pistoncore-v2-src
DATA=/opt/pistoncore-v2-data

# Unraid
SRC=/mnt/user/appdata/pistoncore-v2-src
DATA=/mnt/user/appdata/pistoncore-v2-data

mkdir -p "$SRC" "$DATA"
```

---

## Step 2 — Build and run the container

```bash
git clone https://github.com/jercoates/pistoncore-v2.git "$SRC"
cd "$SRC"
docker build -t pistoncore-v2 .
```

The data directory inside the container is set by `PISTONCORE_DATA_DIR`. The commands below
set it explicitly and mount the same path, so the volume and the code always agree.

### HA OS / Supervised, using SMB

```bash
docker run -d --name pistoncore-v2 \
  -p 7777:7777 \
  -e PISTONCORE_DATA_DIR=/data \
  -v "$DATA":/data \
  --restart unless-stopped \
  pistoncore-v2
```

### HA in Docker, or a host-mounted share (local path)

Add a second volume pointing at Home Assistant's config folder. The container-side path
`/ha-config` is what you'll type into Settings later — use the same string in both places.

```bash
docker run -d --name pistoncore-v2 \
  -p 7777:7777 \
  -e PISTONCORE_DATA_DIR=/data \
  -v "$DATA":/data \
  -v /path/to/homeassistant/config:/ha-config \
  --restart unless-stopped \
  pistoncore-v2
```

Replace `/path/to/homeassistant/config` with the host path your HA container already uses
for `/config` — `docker inspect <your-ha-container>` will show you if you're unsure.

**Port 7777 already taken?** Change the left side only: `-p 7788:7777`, then browse to
`:7788`.

Confirm it came up:

```bash
docker ps --filter name=pistoncore-v2
docker logs -f pistoncore-v2
```

---

## Step 3 — Create a Home Assistant long-lived token

In Home Assistant: click your **user name** (bottom left) → **Security** tab → scroll to
**Long-Lived Access Tokens** → **Create Token**. Name it `PistonCore`.

**Copy it immediately — HA shows it exactly once.**

Use an account that can create helpers. On first load PistonCore creates one `input_select`
called **PistonCore Location Mode** (`input_select.pistoncore_location_mode`, seeded with
Day / Evening / Night / Away) to back webCoRE's Location Mode, which HA has no native
equivalent for. Its entity id is then written into settings, so later loads reuse it and no
duplicate is ever created. If the create fails, the editor still loads with default modes and
retries next time rather than getting stuck.

To use an `input_select` you already have instead, set `location_mode_entity` in
`settings.json` on the data volume. A designated entity that doesn't exist in HA is a hard
error, not a silent fallback — PistonCore won't quietly substitute something else for the
thing you picked.

Deleting this token in HA is how you cut PistonCore off later.

---

## Step 4 — First-run setup

Open `http://<host>:7777` — the host's LAN IP or hostname, not `localhost`, unless you're
sitting at the Docker host. Until credentials are saved, PistonCore sends you to first-run
setup.

Nothing here is a one-way door: **every setting in first-run is also editable later in
Settings**, from the same store. The one exception is permission to write to your HA config,
which is a one-time consent action rather than a stored value.

### 4a. Connect to Home Assistant

**Home Assistant URL** and **Long-lived access token**.

The URL must be reachable **from inside the PistonCore container**, which is the single
most common thing people get wrong:

- **Don't use `http://localhost:8123`.** Inside a container, `localhost` is the container.
- Use the LAN IP or hostname: `http://192.168.1.x:8123`.
- `http://` becomes `ws://` and `https://` becomes `wss://` automatically — enter the
  normal address, not a WebSocket URL.
- HTTPS with a self-signed or internal CA certificate is a certificate-trust problem inside
  the container. Use the plain HTTP LAN address if you have one.

### 4b. Compiled-file write target

Pick your **Write mode**:

**Local path (mounted folder)** — HA's config folder is mounted into the PistonCore
container. Enter the **container-side** path from Step 2 (`/ha-config` if you followed the
example), not the host path.

**SMB (Samba share)** — PistonCore connects to HA's Samba share add-on over the network.
Install the **Samba share** add-on in HA first (Settings → Add-ons → Add-on Store → "Samba
share"), set a username and password in its options, and start it. Then fill in:

- **SMB host** — your HA machine's IP or hostname
- **Share name** — the share exposing HA's `config` folder (defaults to `config`)
- **Username** / **Password** — the credentials from the add-on's own options, **not** your
  HA login

### 4c. Test the write target

Test the write target before going further. It writes a probe file, reads it back, and
deletes it, so a wrong share or a missing mount fails visibly here instead of silently at
your first compile. Don't move past a failure — everything downstream depends on it.

### 4d. Speech, and the rest

Settings also carries a **Default TTS engine**, used by any piston with a Speak command —
the speakers come from the piston itself, this is just which engine renders the audio. You
can set it now or leave it until you write a piston that talks.

---

## Step 5 — Let HA load PistonCore's folders

PistonCore needs two include lines in `configuration.yaml` so HA picks up what the compiler
writes:

```yaml
automation pistoncore: !include_dir_merge_list pistoncore/automations/
script pistoncore: !include_dir_merge_named pistoncore/scripts/
```

**You can add these yourself and skip the rest of this step.** If you'd rather PistonCore do
it, it reads the file, shows you the exact edits, and applies them only when you click —
taking a timestamped backup (`configuration.yaml.pistoncore-backup-YYYYMMDD-HHMMSS`) in the
same folder before it writes, and creating the two folders so the include directives don't
error on a missing path.

**One edit may surprise you.** If your `configuration.yaml` has a plain
`automation: !include automations.yaml` line, it gets **renamed** to
`automation ui: !include automations.yaml` (same for `script:`). YAML can't have two keys
named `automation`, so once a labeled block exists the stock line has to be labeled too. Your
UI-created automations are unaffected — HA still loads them from the same file.

**It refuses rather than guessing.** If your `automation:` or `script:` key is block-style
(rules written inline rather than a one-line `!include`), or the file has no recognizable
top-level keys, PistonCore stops and hands you the lines to paste in yourself. A line-based
edit it doesn't fully understand is not a risk worth taking.

**Then restart Home Assistant** (or reload all YAML). New include lines aren't picked up by
an automation reload alone.

---

## Step 6 — Verify

1. In the editor, create a trivial piston — one trigger, one action, something harmless you
   can watch.
2. Save it. Compile runs automatically on save.
3. Check the file landed in `pistoncore/automations/` under HA's config folder.
4. In HA: **Developer Tools → YAML → Check configuration**, then reload automations.
5. Confirm the automation appears in HA's automation list, then trigger it and watch what
   actually happens.

PistonCore runs HA's own `check_config` before a deploy goes live and stops the deploy on a
failure — but that validates schema, not behavior. **Point 5 above — actually triggering it
and watching — is the part that matters.** Compiling is not the same as tested.

---

## Optional pieces

### PyScript

**Not required.** Simple pistons compile to plain HA automations with no external
dependencies. Pistons using formulas, loops, variables, event blocks, or computed messages
route to PyScript instead.

Install it from HACS (search "pyscript") whenever you need it — nothing breaks in the
meantime. **PistonCore deliberately does not add a `pyscript:` key to your
`configuration.yaml`**, because an unknown integration key breaks HA config validation when
PyScript isn't installed. Follow PyScript's own setup instructions for that part.

### Test devices

Virtual devices for behavioral testing — clone a device you own, or create a type you don't
have, then poke it by hand and watch what the piston does with nothing real switching.

**Installing them is a separate, explicit step.** PistonCore shows you what it will copy
into your HA config and asks first. **Home Assistant needs a restart** to pick them up.
Removing them removes the virtual devices and nothing else. Built, but only lightly tested —
see [VIRTUAL_DEVICES_SPEC.md](VIRTUAL_DEVICES_SPEC.md).

---

## Updating

There are two kinds of update and they work differently.

### Compiler data — no rebuild needed

The compiler's knowledge lives in editable data on your data volume under `customize/` — the
vocab (every Home Assistant service and field name the compiler uses), the picker capability
map, the routing table, and the emission templates. PistonCore can pull the current official
versions from the repo without any Docker commands at all. This is the normal way to get a
translation fix.

Your edits are safe. On every startup PistonCore compares three copies of each file: what
the image ships, what it shipped last time, and what you're actually running. If you never
touched a file, it's refreshed from the new build. If you did, **your version wins** — JSON
files deep-merge so shipped updates still reach every key you didn't touch, and templates
are left exactly as you wrote them and reported as needing attention. Anything it can't
reconcile is copied to `customize/.replaced/` first. Nothing is destroyed.

One known limit: the JSON overlay carries additions and changes, not deletions. A key you
deleted comes back on the next update. Deleting from the vocab isn't how you turn something
off anyway — that's `"ha": "n/a"`.

### The application itself — rebuild and recreate

**This is where people trip up.** The container keeps running old code until you rebuild
*and* recreate it. `docker restart` does nothing.

```bash
cd "$SRC"
git pull                       # must say "Fast-forward"
git log --oneline -1           # confirm the commit you expect

docker build -t pistoncore-v2 .
docker rm -f pistoncore-v2     # remove the old container...
docker run -d --name pistoncore-v2 \
  -p 7777:7777 \
  -e PISTONCORE_DATA_DIR=/data \
  -v "$DATA":/data \
  --restart unless-stopped \
  pistoncore-v2
```

Re-use **exactly** the flags you ran originally, including `-v .../ha-config` if you're on
the local-path write mode. Your pistons, settings, and customizations live on the data volume
and survive this.

If changes still don't appear after a rebuild, Docker used a cached layer — add `--no-cache`
to the build. If only the *UI* looks unchanged, it's your browser: Ctrl+Shift+R or an
incognito window.

---

## Removing PistonCore

Your automations are yours. Removing PistonCore doesn't take them with it.

```bash
docker rm -f pistoncore-v2
docker rmi pistoncore-v2
```

What stays behind — the same five places, in reverse:

- **Compiled automations** in `pistoncore/automations/` and `pistoncore/scripts/` keep
  running natively. Complex pistons keep running as long as PyScript stays installed.
- **The `configuration.yaml` lines** stay valid as long as those folders exist. If you delete
  the folders, remove the lines too — `!include_dir_*` on a missing folder is an HA config
  error. The `automation ui:` / `script ui:` renames can stay as they are, or go back to
  `automation:` / `script:` once no labeled block is left. Your backup copies are still
  sitting next to `configuration.yaml` if you'd rather restore one.
- **The Location Mode helper** (`input_select.pistoncore_location_mode`) deletes from HA's
  helpers page if you don't want it.
- **The test-devices integration**, if installed, removes separately from
  `custom_components/`.
- **Piston variable helpers** live in `pistoncore_packages/`. Delete the folder and the
  `packages:` line to remove them all at once, or delete individual helpers from HA's
  helpers page. Any automation still reading one will simply see it as unavailable — it
  will not stop the rest of the automation from running.

Also: **the data folder** holds your pistons, settings, and compiler customizations. Keep it
if there's any chance you'll come back — it's your only copy of your piston JSON unless you
exported it. And **the HA token** deletes from your profile's Security tab.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Editor won't load at `:7777` | Container isn't running (`docker ps`), port conflict, or `localhost` from a different machine. Check `docker logs pistoncore-v2`. |
| "Could not connect to HA" | The URL isn't reachable *from inside the container* — `localhost` instead of the LAN IP is the usual culprit. Also check port and `http` vs `https`. Fix it in Settings. |
| "HA authentication failed" | Token pasted wrong (trailing space, truncated) or deleted in HA. Create a fresh one and paste it in Settings. |
| Write probe fails, local path | You entered the host path instead of the container-side path, or the `-v` flag is missing. `docker inspect pistoncore-v2` shows what's actually mounted. |
| Write probe fails, SMB | Samba add-on not started, wrong share name, or you used your HA login instead of the credentials set in the add-on's options. |
| "SMB mode needs the 'smbprotocol' package" | The image was built without it. Rebuild from current source. |
| PistonCore refuses to edit `configuration.yaml` | Your `automation:` or `script:` key is block-style rather than a one-line `!include`. It gives you the exact lines — add them by hand, then continue. |
| Files write, but HA doesn't see the automations | HA hasn't restarted since the include lines were added. New includes need a restart or a full YAML reload, not just an automation reload. |
| Pistons or settings vanished after an update | The data volume wasn't mounted where the app reads it. Check that `-v "$DATA":/data` and `-e PISTONCORE_DATA_DIR=/data` are both present and agree. |
| Location Mode empty or "(unknown)" | The helper wasn't created — usually a token that can't create helpers. Check the container log, fix the token, reload. |
| Devices missing or wrong in the picker | Report it. Device mapping is research-backed and not every device type has been live-checked — this is the most useful alpha feedback there is. |
| Piston compiles but behaves wrong | Report it with the piston JSON. Same reason. |

---

## Where this is going

An HA add-on path — sidebar entry, automatic supervisor auth, no token and no write-target
setup — is planned. The auth side already exists in the client (it picks up
`SUPERVISOR_TOKEN` automatically when present); what's missing is the add-on packaging.
Docker-only is deliberate for now: the add-on shouldn't get built on top of an install path
that isn't solid yet.
