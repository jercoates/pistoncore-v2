# PistonCore Backend

This folder contains the PistonCore backend — the Python FastAPI application that stores pistons, compiles piston JSON into native Home Assistant files, and exposes a REST API for the frontend.

---

> **IMPORTANT — First-Run Setup**
>
> On first startup (when `ha_config_path` is configured), PistonCore automatically
> adds two lines to your Home Assistant `configuration.yaml` to register its
> automation and script folders. **A one-time Home Assistant restart is required**
> after this happens before script pistons can be deployed. Automation pistons
> work immediately without a restart. You will see a warning in the PistonCore UI
> until a script piston deploys successfully.

---

## Files

| File | What it does |
|---|---|
| `compiler.py` | Compiles piston JSON → two HA YAML strings (automation + script). Matches COMPILER_SPEC.md. |
| `main.py` | FastAPI app entry point. Runs on port 7777. Runs HA config setup on startup. |
| `api.py` | All REST API endpoints. See endpoint list below. |
| `storage.py` | All filesystem I/O — piston JSON files, globals store, config. Never called directly by the compiler. |
| `ha_client.py` | All HA communication via WebSocket. Handles auth, caching, device/service queries, and service calls for reload. |

## Running Locally

```bash
cd backend
pip install fastapi uvicorn jinja2 pyyaml websockets
PISTONCORE_DATA_DIR=./testdata PISTONCORE_TEMPLATE_DIR=../pistoncore-customize/compiler-templates/native-script/ uvicorn main:app --host 0.0.0.0 --port 7777 --reload
```

The `PISTONCORE_DATA_DIR` env var lets you point storage at a local test folder instead of `/pistoncore-userdata/`.

## API Endpoints

| Method | Path | What it does |
|---|---|---|
| GET | /pistons | List all pistons (summary only) |
| GET | /pistons/{id} | Get full piston JSON |
| POST | /pistons | Create a new piston |
| PUT | /pistons/{id} | Save piston to Docker volume (no HA write) |
| DELETE | /pistons/{id} | Delete piston from storage |
| POST | /pistons/{id}/compile | Compile and return YAML strings (no HA write) |
| POST | /pistons/{id}/deploy | Compile + write YAML files to HA config dir + call reload |
| GET | /globals | List global variables |
| POST | /globals | Create a global variable |
| DELETE | /globals/{id} | Delete a global variable |
| GET | /config | Get runtime config (token redacted) |
| PUT | /config | Update runtime config |
| GET | /health | Health check |

## Two Save Operations

There are two distinct save operations — the frontend must make this clear to users:

1. **Save** (`PUT /pistons/{id}`) — writes the piston JSON to the Docker volume. Fast, always works, no HA involvement. This is what the Save button does.
2. **Deploy** (`POST /pistons/{id}/deploy`) — compiles the piston and writes the YAML files directly to the HA config directory (via `ha_config_path`), then calls `automation.reload` and `script.reload`. Requires `ha_config_path` and `ha_url`/`ha_token` configured.

## Deploy — HA Config Path

The deploy endpoint writes files directly to the HA config directory. Set `ha_config_path` in PistonCore settings to the path of your HA config directory:

- **Addon:** `/config` (set automatically in future addon packaging)
- **Docker with volume mount:** wherever you mount the HA config dir
- **Docker with Samba:** the mount point of your HA Samba share

On first startup with `ha_config_path` set, PistonCore appends two lines to
`configuration.yaml` and creates the `automations/pistoncore/` and
`scripts/pistoncore/` subdirectories. A one-time HA restart is required after
this for script pistons. Automation pistons work immediately.

## Compiler Quick Test

Run the compiler standalone against the driveway lights test piston (COMPILER_SPEC Section 18):

```bash
cd backend
PISTONCORE_TEMPLATE_DIR=../pistoncore-customize/compiler-templates/native-script/ python compiler.py
```

Expected output matches the hand-written example in COMPILER_SPEC.md Section 18.

## For AI Assistants

Read DESIGN.md v1.1 and COMPILER_SPEC.md before modifying any file in this folder.

- `compiler.py` — each method references the COMPILER_SPEC section it implements. Add new statement types by adding an `elif` in `_compile_sequence()` and a `_compile_<type>()` method below.
- `api.py` — deploy endpoint writes files to `ha_config_path` and calls HA reload via `ha_client.call_service()`.
- `ha_client.py` — all HA communication. WebSocket only — no REST calls. Add new HA queries here.
- `storage.py` — all file paths go through this module. Do not read or write files from `api.py` or `compiler.py` directly.
- `main.py` — startup hook `_setup_ha_config()` handles configuration.yaml setup per DESIGN.md Section 19 exception.

Do not change the design documents. The backend serves the spec — not the other way around.
