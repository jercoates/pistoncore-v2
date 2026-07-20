# Compiler Source Mining — External References for PistonCore v2

Purpose: distilled, verified facts from adjacent "visual/config → HA YAML" projects,
to feed Claude Code when generating the YAML compiler. Everything here is marked with
verification status and source per the standing documentation rule.

---

## 1. HA automation YAML key evolution (affects compiler output shape)

- **`trigger`/`condition`/`action` → `triggers`/`conditions`/`actions` (plural).**
  Verified — Peyanski blog documenting the 2024.8 syntax change, and HA docs
  automations page (2026.7.2), Oct 2024 / accessed Jul 2026. The singular `platform`
  key inside a trigger was also renamed to `trigger`.

- **Both singular and plural forms still coexist in the wild and are accepted by HA.**
  Verified — home-assistant-vibecode-agent CHANGELOG 2.10.38 (2026-02-18): they added a
  Pydantic validator normalizing plural→singular because the modern UI emits plural but
  older tooling emits singular. Accessed Jul 2026.
  - **Decision — PistonCore choice:** emit **plural** (`triggers`/`conditions`/`actions`)
    as primary, since that is what the modern UI and `automations.yaml` write today.
    Keep a singular-accepting path only if `ha core check` ever rejects plural (it does not).

- **Purpose-specific triggers/conditions graduated Labs→default in 2026.7, and several
  keys were renamed so "the old keys no longer work."**
  Verified — HA 2026.7 release blog (via search snippet), and issue #166950
  (behaviour options: `any`→`each`, `last`→`all`, `first` unchanged), Mar 2026 / Jul 2026.
  - **Decision — PistonCore choice (already locked):** compiler emits **classic
    primitives only** (`state`, `numeric_state`, `time`, `template`, `sun`, etc.), never
    purpose-specific triggers. This sidesteps the entire rename-churn surface. Reconfirmed
    by this mining pass — the 2026.7 renames are exactly the volatility we're avoiding.

---

## 2. Node-RED action node — target/data separation (the important structural lesson)

Node-RED's `node-red-contrib-home-assistant-websocket` is the largest existing
"visual → HA" translation layer. It does NOT compile to YAML (runs against the websocket
API at runtime), so it's an architectural contrast, not a drop-in reference. The valuable
part is how it structures a service call.

- **A service call is split into three distinct objects: `action`, target, and `data`.**
  Verified — action node docs + JSONata cookbook, accessed Jul 2026.
  - `action`: the `domain.service` string, e.g. `climate.set_temperature`,
    `light.turn_on`, `input_select.select_option`.
  - target: separate fields — `floorId`, `areaId`, `deviceId`, `entityId`, `labelId`
    (arrays). In HA YAML terms this is the `target:` block.
  - `data`: the service-data payload (e.g. `temperature`, `brightness`), JSONata or JSON.

- **entity_id belongs in the target, NOT in `data`. Putting it in `data.entity_id`
  is now an explicit error.**
  Verified — node-red-contrib-home-assistant-websocket CHANGELOG 0.66.0 (2024-08-16):
  "Entity IDs incorrectly placed in `targets.entity_id` instead of `data.entity_id`
  will now trigger errors" (and the device-action fix to send entity to HA). Accessed
  Jul 2026.
  - **Decision — PistonCore choice:** compiler must emit entity targeting under
    `target: { entity_id: [...] }`, keeping `data:` for service parameters only. Do not
    fold `entity_id` into `data:` even though older HA still tolerates it. This mirrors
    the modern service-call schema and avoids the exact trap the largest visual tool
    had to add error-checking for.

- **`domain` + `service` as separate input properties are deprecated in favor of a single
  `action` string.**
  Verified — same CHANGELOG (call-service node renamed to `action` node; domain/service
  input properties deprecated, slated for removal in 1.0). Accessed Jul 2026.
  - **Note for compiler:** internally we can carry domain and service separately (cleaner
    for vocab lookups), but the emitted YAML uses the unified `action: domain.service`.

- **The `homeassistant.turn_on` / `homeassistant.turn_off` domain is a legitimate
  cross-domain service** for toggling mixed entity types in one call.
  Verified — action node tips/tricks page (flow uses `action: homeassistant.turn_{{payload}}`
  across light + area targets), accessed Jul 2026.
  - **Possible use:** webCoRE "Toggle"/generic on-off across heterogeneous device lists
    could compile to `homeassistant.toggle`/`turn_on`/`turn_off` rather than resolving
    each entity's own domain. Assumed — needs test against DEVICE_PAYLOAD_SPEC grouping.

---

## 3. Blueprints / `!input` (inverse reference, not a compile target)

- HA blueprints use `!input <name>` substitution and the automation editor serializes
  editor state to YAML. This is the *inverse* of the compiler (editor→YAML vs
  pistonJSON→YAML), so it's a shape reference only.
  Assumed — general HA blueprint knowledge; not re-verified this pass. Flag if we ever
  want blueprint output as an export format (we currently do not — YAML automation is the
  primary compile path, PyScript the forced exception).

---

## 4. Validation path (already in flight, cross-referenced here)

- `ha core check` / `homeassistant.core.check_config` is the pre-deploy gate. Node-RED's
  runtime-error approach (reject bad `data.entity_id` at call time) is *not* available to
  a compile-ahead tool — we must catch shape errors before deploy.
  - **Decision — PistonCore choice (already locked):** dedicated test instance with dummy
    helpers + `ha core check` API integration is the equivalent of Node-RED's runtime
    validation, shifted left to compile time.

---

## Open items to verify against live HA (flag for a test-instance session)

1. Does `ha core check` accept plural `triggers/conditions/actions` cleanly on 2026.7.x?
   (Expected yes — it's what the UI writes. Assumed — needs test.)
2. Confirm `target: { entity_id: [...] }` vs legacy `data: { entity_id: ... }` both pass
   `ha core check`, and standardize on target. (Assumed — needs test.)
3. `homeassistant.toggle` across mixed domains for webCoRE generic toggle — behavior on a
   list spanning light + switch + fan. (Assumed — needs test.)

---

*Source list (accessed Jul 2026): HA automations YAML docs (2026.7.2); HA 2026.7 release
blog; core issue #166950; Peyanski HA syntax blog (2024); node-red-contrib-home-assistant-
websocket CHANGELOG (0.66.0, main) + action node docs/cookbook; home-assistant-vibecode-
agent CHANGELOG 2.10.38.*
