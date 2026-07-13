# PistonCore — Speak / Announce Action Contract

**Version:** 0.3 (DRAFT — standalone)
**Status:** Pre-coding contract. NOT yet integrated into WIZARD_SPEC.md / COMPILER_SPEC.md.
**Last Updated:** June 2026 (Session 73 — verified/assumed ledger added)
**Authority:** WebCoRE `with` / `do` / `Speak text` / `Set Volume` task model
(piston.module.html + WebCoRE source archived in Session 14 chat).

---

## LEDGER — Verified vs. Assumed (read this to audit the spec)

Default convention: **the spec records Jeremy's DECISIONS.** Anything Claude *assumed*
to fill a gap is listed in the ASSUMED column below and is **never load-bearing** — it
is a proposal awaiting Jeremy's call, freely overridable in coding without archaeology.
If it is not in the ASSUMED list, it is either a verified fact or a Jeremy decision.

### VERIFIED (live HA / WebCoRE source — facts, not choices)
- `tts.speak` takes `target.entity_id` (the engine), `data.media_player_entity_id` (the
  output), and `data.message`. (HA docs, Session 73.)
- `cache: true` is a real `tts.speak` data param; standard in Piper/Wyoming usage; it is
  the offline-clip-caching equivalent of Hubitat's behavior. (HA docs / community.)
- SSML rendering is engine-dependent: SSML-capable engines require `options.text_type:
  ssml`; Piper has no SSML support at all. (HA docs, Session 73.)
- WebCoRE reference structure: Speak is a `do` task inside a `with` block; Set Volume is a
  separate sibling task; no engine appears in the piston. (WebCoRE trace, Session 72.)
- The reference piston's `<prosody>` was a hand-added flourish, not part of WebCoRE's
  model. (Jeremy, Session 73.)

### DECIDED (Jeremy's calls)
- Engine is resolved at compile time from a global setting, not stored in the node.
- Compiler is read-only; incompatibility is surfaced (front-door indicator + piston
  status-screen banner, per CLAUDE.md's UI split — no separate debug page), never mutates
  JSON.
- SSML passed verbatim; compiler does NOT inject `text_type` or strip SSML; rate control
  is an engine/voice concern (`length_scale` for Piper), out of scope for the node.
- Build queues behind GAP-S72-1 (multi-task with-block).

### ASSUMED by Claude (NOT load-bearing — override freely in coding)
- All field/key names in Section 4 (`with_block`, `entity_ids`, `tasks`, `command`,
  `params`, `set_volume`, `speak_text`, `message`, `volume`) — PROPOSED only, must be
  reconciled against PISTON_FORMAT.md. Section 7 tracks this.
- That Set Volume already exists as a reusable media_player task type (Section 7 item 4).
- The author-time wizard gate logic (PLAY_MEDIA bit + tts.* existence) as the gating
  rule — proposed shape, not a verified requirement.
- `cache` emitted as default-on with no user toggle — a proposed default, not a decision.

---

## 0. Why this document exists

Speak/TTS is core to Jeremy's real automations and has had zero wizard work
(GAP-S71-4). Before any code is written, the JSON contract that the editor/wizard
produces and the compiler consumes must be fixed in writing. The drift-class bugs
this project has fought (`service_call` vs `with_block`, `entity_id` vs `entity_ids`,
indexed-key params) all came from the frontend and compiler each assuming a JSON
shape with no written contract between them. Speak is a new task shape, so it gets
pinned here first.

This file will be folded into WIZARD_SPEC.md (editor/wizard side) and COMPILER_SPEC.md
(compiler side) as those areas are coded. A TASKS.md entry tracks final spec integration.

---

## 1. First principle — what defines "done"

**PistonCore is a recreation of WebCoRE for Home Assistant, as faithfully as HA allows.**

The editor's job is to reproduce WebCoRE's visual logic exactly. What the user *sees*
in the editor is how they know what the piston does — the visual IS the contract with
the user. How the automation actually runs under the hood (which HA service, which TTS
engine, how volume is scaled) has no bearing on the visual and is entirely hidden.

Therefore:

- **Editor/visual fidelity is the definition of done.** Verified by eye against the
  WebCoRE source piston — it matches character-for-character or it does not.
- **The compiler is invisible plumbing.** Its only obligation is: given the fixed JSON
  the editor produced, emit HA that behaves as the visual promises.
- **Under-the-hood choices must never leak upward into the editor display.**

---

## 2. The WebCoRE reference (authority)

From the live WebCoRE trace (Hubitat HubwebCoRE, confirmed Session 72):

```
with {@Announcement_Sonos}        /* #13 */
do
    Set Volume to 70;             /* #14 */
    Speak text "{Message}";       /* #15 */
end with;
```

Observations that fix the contract:

1. **Speak is a task inside a `with` block — NOT a standalone action node and NOT a
   distinct top-level type.** The `with {device}` owns an ordered list of `do` tasks.
   "Speak text" is one task type among others.
2. **Set Volume is a separate sibling task**, ordered before Speak inside the same
   with-block. Volume is NOT a field on the Speak task.
3. **No engine appears anywhere in the piston.** `Speak text "{Message}"` carries no
   TTS-engine reference. The engine is environment configuration, resolved outside the
   piston — i.e. at compile time, from a global setting.
4. **The message is a string with variable interpolation** (`"{Message}"`). The Message
   variable was built earlier with Set variable and may contain SSML
   (`<prosody rate='slow'>$currentEventDevice, Opened</prosody>`). The message field must
   pass whatever the variable holds — literal text, variable tokens, SSML — through
   untouched. **SSML rendering is engine-dependent and explicitly NOT guaranteed** (see
   Section 5.5). In the reference piston the `<prosody>` was a hand-added flourish, not
   part of WebCoRE's model; it is cosmetic, not load-bearing.

---

## 3. Editor / visual contract (AUTHORITATIVE — the deliverable)

The editor renders the Speak task and its containing with-block exactly as WebCoRE
displays them. This is a pure deterministic projection from the rigid JSON — one node
shape, one display form, no judgment calls.

### 3.1 Rendered display

Inside a with-block, each Speak task renders as:

```
Speak text "<message>";
```

A sibling Set Volume task renders as:

```
Set Volume to <n>;
```

The enclosing block renders as WebCoRE does:

```
with {<device or @global>}
do
    <task>;
    <task>;
end with;
```

`with`, `do`, `end with` are display artifacts only — never editable nodes, never
stored. (Consistent with the core rendering invariant in STATEMENT_TYPES.md.)

### 3.2 Wizard task editor

The Speak task editor mirrors WebCoRE's `dialog-edit-task` template (pull the exact
template from the Session 14 chat before coding the form). At minimum it provides:

- A message field: free text + `$variable` insertion (literals and variables mixed),
  SSML passed through verbatim.
- (Set Volume remains its own task editor, unchanged — it is not part of the Speak form.)

### 3.3 Where Speak appears in the wizard (author-time gate)

Speak is offered as an available **task type inside a with-block** (the `do` task list),
NOT as a synthetic command competing in the flat `media_player.*` service list.

The author-time gate decides whether Speak is offered:

```
all resolved entities in the with-block are domain media_player?
  AND every resolved player advertises supported_features & 512 (PLAY_MEDIA)?
  AND at least one tts.* engine entity exists in HA?
    → offer "Speak text" as an available do-task
```

- PLAY_MEDIA is intersected across all selected physical devices (union within a
  device's sub-entities, then intersect across devices — the locked capability pattern).
- This gate is **best-effort and author-time only.** It can be stale. The authoritative
  compatibility check happens in the compiler (Section 5). The wizard gate exists to stop
  the user building an obviously-broken task, not to guarantee correctness.

---

## 4. JSON contract (the shape that backs the visual)

The JSON shape is **dictated by the WebCoRE structure**, not chosen freely. Speak is a
task in a with-block because WebCoRE makes it one. This shape backs the Section 3 visual
and is the fixed input the compiler consumes.

> NOTE — field names below are PROPOSED and must be reconciled against the actual
> with_block / task schema in PISTON_FORMAT.md during coding. The intent is fixed
> (Speak = a task in a with_block; volume = a separate sibling task; no engine in the
> node; message = token-interpolated string). Exact key names get locked against the
> existing schema, NOT invented here. This is where `entity_id` vs `entity_ids` and
> `service_call` vs `with_block` must be checked, not assumed.

Illustrative (subject to schema reconciliation):

```json
{
  "type": "with_block",
  "entity_ids": ["media_player.sonos_kitchen", "media_player.sonos_living"],
  "tasks": [
    {
      "type": "task",
      "command": "set_volume",
      "params": { "volume": 70 }
    },
    {
      "type": "task",
      "command": "speak_text",
      "params": { "message": "{Message}" }
    }
  ]
}
```

Fixed by the WebCoRE structure:

- Speak is a `task` within `with_block.tasks` — never a standalone node, never a top-level
  type.
- Set Volume is a separate sibling `task`, ordered before the speak task.
- The node carries **no TTS engine** — engine is resolved at compile time from a global.
- `params.message` is a single string containing literal text + variable tokens
  (`$Var` / `{Var}` per the project's variable syntax), SSML preserved verbatim.
- Volume scale stored in the node is a UI/visual decision (WebCoRE shows `70`); any
  conversion to HA's 0.0–1.0 happens in the compiler, never in the stored JSON.

---

## 5. Compiler contract (read-only, invisible plumbing)

### 5.1 Absolute rule

**The compiler reads the JSON. It NEVER writes, reshapes, or mutates it.** The JSON is
authored by the editor/wizard and is the source of truth. The compiler is input-only.
This is the rule whose violation has bitten the project before.

### 5.2 Live HA lookups at compile time

The compiler MAY pull live HA information at compile time to make its hidden translation
correct. These lookups inform the OUTPUT only — never the source JSON:

- **TTS engine selection** — resolve the engine from the global "default TTS engine"
  setting (a `tts.*` entity discovered from HA states). The engine is not in the piston.
- **Device compatibility** — verify each resolved `media_player` in the with-block can
  actually accept TTS (live `supported_features` / PLAY_MEDIA bit at compile time).

### 5.3 Error handling — surfaced, never mutation

If the compiler finds an incompatible device (cannot speak) or no available TTS engine:

- It does **not** edit the JSON.
- It does **not** silently drop the Speak task.
- It writes a clear, specific error identifying the offending device/engine and why it
  failed, shown on the two surfaces CLAUDE.md's UI split defines (front-door indicator +
  the piston's own status-screen banner) — there is no separate debug page.

The piston source stays untouched regardless of compile outcome.

### 5.4 Emitted HA (per Speak task in a with-block)

For each with-block containing a speak task, emit in order:

1. If a Set Volume task is present, `media_player.volume_set` for the with-block's
   resolved `entity_ids` (volume converted from the stored UI scale to HA's 0.0–1.0
   here, in the compiler).
2. `tts.speak`:
   - target = the global TTS engine entity (`target.entity_id`, a `tts.*` entity)
   - `data.media_player_entity_id` = the with-block's resolved `entity_ids`
   - `data.message` = the compiled Jinja2 template produced from `params.message`
     (variable tokens → variable refs; message contents preserved verbatim).
   - `data.cache: true` — emitted by default. This is the HA-side equivalent of the
     offline clip caching Jeremy relies on under Hubitat: HA generates the audio once and
     persists it, so a self-hosted engine (Piper) does not re-synthesize every fire and
     announcements survive without a live cloud dependency. Confirmed standard in every
     Piper/Wyoming `tts.speak` example. Whether `cache` is exposed as a user toggle or
     hardcoded is a later UI decision; default-on is the contract.

The verified `tts.speak` shape (HA docs, Session 73):

```yaml
action: tts.speak
target:
  entity_id: tts.piper          # the engine (global setting)
data:
  cache: true
  media_player_entity_id: media_player.sonos_kitchen   # the output(s)
  message: "{{ ...compiled Jinja2... }}"
```

`target.entity_id` selects the engine; `data.media_player_entity_id` selects the
output device(s). These are two distinct fields and must not be conflated — the engine
is never a media_player and the media_player is never the target.

All values go through Jinja2 (standing project rule — no exceptions). The
variable-token → Jinja substitution MUST reuse the single canonical substitution
function used elsewhere in the compiler; do not introduce a second variable-substitution
path for Speak.

PyScript target: same service call via the PyScript service-call mechanism, preserving
volume-then-speak ordering. (Detail confirmed during compiler work.)

### 5.5 SSML — passthrough, not rendering (feasibility confirmed Session 73)

The message string may contain SSML, but **the compiler does not guarantee it renders.**
SSML interpretation is entirely a property of the resolved TTS engine, not of PistonCore:

- **Engines that honor SSML** (Google Cloud, Polly, etc.) require an explicit opt-in,
  typically `options.text_type: ssml` in the `tts.speak` call (default is `text`). Plain
  passthrough alone is a no-op — the tags speak as literal characters unless the engine
  is told to parse them.
- **Piper (Jeremy's local engine) has no SSML support at all.** `<prosody>` and any other
  tags are ignored/spoken literally. There is no `text_type` option for it.

Contract decision: the message is passed verbatim; the compiler does **not** inject
`text_type: ssml` and does **not** strip SSML. Rendering SSML is out of scope for the
Speak action. If per-engine SSML opt-in is ever wanted, it belongs in the global
engine/options configuration, not in the Speak node.

Rate/cadence control (the original `<prosody rate='slow'>` intent) is likewise an
engine concern, not a node concern. For Piper, the local equivalent is the voice's
`length_scale` (utterance-wide speed), configured at the voice/Wyoming level — never
in the piston. This keeps the Speak action engine-agnostic and fully local-capable.

---

## 6. Data availability (confirmed Session 72)

Everything the gate and compiler need is already in the single HA `get_states` call —
no new HA round-trips required:

- **PLAY_MEDIA bit:** `attributes.supported_features` is read in `ha_client.py`
  `_fetch_devices` (line ~375) but currently DROPPED — the device dict (line ~384) keeps
  only entity_id/friendly_name/domain/area/device_id. Carrying `supported_features`
  through `_fetch_devices` and then through `_groupDevices` (wizard-core.js ~220) is the
  plumbing needed for the author-time gate.
- **TTS engine list:** `tts.*` entities are in the same `get_states` result but filtered
  out by `ALLOWED_DOMAINS` (ha_client.py ~372). A small enumeration of `tts.` entities
  feeds the global default-engine setting.

---

## 7. Open items to reconcile during coding (NOT decisions — schema checks)

These are not free choices — they are reconciliations against existing rigid structure:

1. Exact field/key names in Section 4 vs the real with_block/task schema in
   PISTON_FORMAT.md (the `entity_id` vs `entity_ids`, `service_call` vs `with_block`
   problem area).
2. The exact `dialog-edit-task` template from Session 14 for the Speak form layout.
3. Where the global "default TTS engine" setting lives (globals store vs a separate
   settings area) and how it is populated from discovered `tts.*` entities.
4. Volume task: confirm Set Volume already exists as a media_player task type and reuse
   it rather than adding anything for Speak.

---

## 8. Summary — the contract in one line each

- **Feasibility (Session 73):** CONFIRMED possible in HA, fully local. Message-from-live-data
  → native Script `variables:` block with Jinja2 interpolation; spoken by Piper, cached
  via `cache: true`, played on Sonos, zero cloud/internet dependency. No PyScript required
  for the variable mechanic. The only thing that ever pulled toward cloud was SSML rate
  control, which is cosmetic and out of scope.
- **Editor:** Speak renders as a `do` task in a `with` block, Set Volume as a sibling
  task, matching WebCoRE exactly. This is the deliverable.
- **JSON:** Speak is a task in `with_block.tasks`; no engine; message is a
  token-interpolated string (SSML permitted but not rendered-guaranteed). Shape dictated
  by WebCoRE, reconciled to existing schema.
- **Compiler:** read-only; pulls live HA at compile time for engine + compatibility;
  emits volume_set + tts.speak (with `cache: true`); SSML passed verbatim, never opted-in
  or stripped; on incompatibility surfaces the error (front-door + status-screen banner,
  no separate debug page); never touches the JSON.

---

## CONVENTION NOTE — for the session prompt and TASKS.md

**New standing convention (add to session prompt + TASKS.md):**

> When Claude writes or edits a spec, it MUST mark anything that is Claude's own
> assumption (a gap Claude filled, a proposed name/shape/rule Jeremy did not explicitly
> decide) as ASSUMED. Decisions do not need marking — the default is that a spec records
> Jeremy's decisions. Marking the assumptions is what keeps the rare assumption visible
> instead of letting it masquerade as a settled decision. Assumptions are never
> load-bearing and are freely overridable in coding. Maintain a "Verified vs. Assumed"
> ledger near the top of each standalone spec.

This exists because the project's drift-class bugs came partly from Claude's gap-filling
assumptions hardening into apparent "decisions" across sessions that neither party could
later distinguish. The existing prompt already states Jeremy will break any "rule" that
blocks coding a working product — this convention is the complement: it keeps spec rules
honestly labeled so Jeremy knows which ones are real decisions worth keeping and which
are Claude's proposals safe to break.
