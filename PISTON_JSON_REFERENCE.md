# PISTON_JSON_REFERENCE.md — The webCoRE Piston JSON Format

**Status:** Draft 1 — extracted from `dashboard/js/modules/piston.module.js` (the vendored editor is the code that *authors* this JSON, so it is the primary source for structure). Engine-side semantics not visible in the editor are tagged TO VERIFY (check against webcore-piston.groovy when needed).
**Authority:** This JSON format is **law** (standing v2 rule: the piston JSON as webCoRE emits it is law; PistonCore adapts to it, never the reverse). This document *describes* the law; where it and the dashboard source disagree, the source wins and this doc gets fixed.
**Consumers:** the compiler (reads it), import/export (moves it), and **AI authoring** — an AI that produces JSON conforming to this document yields a piston the editor renders and the compiler compiles. That is the design goal of this file.
**Tagging:** `VERIFIED` (read from editor source, with line refs), `TO VERIFY` (engine-side or unexercised), `V2 NOTE` (PistonCore-specific handling).

---

## 0. Transport vs. content

This document describes the piston **content**. In transit (save flow) it is JSON → emoji-encoded → base64 → chunked query params; see SHIM_API_SPEC.md §2/§4.7. At rest and in `piston/get` responses it is a plain JSON object under the `data` key.

All **device references anywhere in a piston are hashed device IDs** (`:` + md5("core." + registry_device_id) + `:`; entity_id for singleton groups) — one ID per grouped physical device, resolved through the shim's resolution map (DEVICE_PAYLOAD_SPEC.md Stages 7–8). Friendly names are never stored in the piston; the editor renders them by ID lookup.

---

## 1. Piston root (VERIFIED piston.module.js:373–402)

```
{
  "o": { ...options, e.g. "cto": 0, "ced": 0, "aps": , "dco": , "des": , "ish": , "mps": , "pep":  },
  "r": [ <restriction>, ... ],       // piston-level restrictions ("only execute if...")
  "s": [ <statement>, ... ],         // the program
  "v": [ <local variable>, ... ],    // piston-local variables
  "z": "<description string>"
}
```
- `o` defaults to `{cto: 0, ced: 0}` (VERIFIED :397). Option key meanings are engine settings (command optimization, event display, logging etc.) — individual meanings TO VERIFY; the compiler should treat unknown `o` keys as pass-through/ignorable, never an error.
- Local variable entry: `{ "n": "<name>", "t": "<type>", "v": <initial value> }` (VERIFIED :2123–2138; names sanitized to `[a-z0-9_]`). Type `"dynamic"` is legal. Device-type variables hold arrays of hashed device IDs.
- Globals are NOT in the piston — they live instance-side (`globalVars`, SHIM_API_SPEC §4.10) and are referenced from operands by `@Name`.

## 2. Statements

### 2.1 Common fields (VERIFIED editStatement init :1089–1140 and save switch :1244–1308)

```
{
  "t":  "<statement type>",     // see 2.2
  "s":  [ ... ],                // child statements (looping/branching types)
  "d":  [ ... ],                // devices (action) — hashed IDs
  "o":  "and"|"or"|...,         // condition grouping operator (if/while/repeat; 'on' forces "or")
  "n":  false,                  // negate conditions
  "a":  "0"|"1",                // async flag
  "di": false,                  // disabled (soft-delete/pause of the statement)
  "tcp":"c"|...,                // task cancellation policy (cancel on condition state change)
  "tep":"",                     // task execution policy
  "tsp":"",                     // task scheduling policy override
  "ctp":"i"|...,                // (switch) case traversal policy
  "sm": "auto"|...,             // statement mode (omitted when "auto" — VERIFIED :1240)
  "z":  "<description>",
  "rop":"and", "rn": false,     // restriction operator/negation (statement-level restrictions)
  "r":  [ <restriction>, ... ]  // statement-level restrictions (present when set)
}
```
Exact value sets for tcp/tep/tsp/ctp come from the dialog templates (piston.module.html) — enumerate there when the compiler needs them; the *defaults* above are VERIFIED. The editor deletes `sm` when "auto", so absent = auto.

### 2.2 Statement types and their specific fields (VERIFIED save switch :1244–1308)

| `t` | Meaning | Type-specific fields |
|---|---|---|
| `"action"` | with-block: do X with devices | `d`: [device ids], `k`: [ <task>, ... ] |
| `"do"` | plain block | `s` |
| `"on"` | on-events-do (trigger block) | `c`: [ <condition>, ... ] (o forced "or", n forced false), `s` |
| `"if"` | if/else-if/else | `c`: conditions, `s`: then-branch, `ei`: [ {o, n, c:[...], s:[...]}, ... ] else-ifs (VERIFIED :1684 — elseIf = `{o:'and', n:false, c:[], s:[]}`), `e`: else-branch statements |
| `"switch"` | switch/case | `lo`: switched operand, `cs`: [ <case>, ... ], `e`: default-branch statements, `ctp` |
| `"for"` | counted loop | `x`: loop variable name, `lo`: from, `lo2`: to, `lo3`: step (all operands), `s` |
| `"each"` | for-each device | `x`: loop variable name, `lo`: device-list operand, `s` |
| `"while"` | while loop | `o`, `n`, `c`: conditions, `s` |
| `"repeat"` | repeat-until | `o`, `n`, `c`: conditions, `s` |
| `"every"` | timer statement | `lo`: interval value, `lo2`: time anchor (Date collapsed to minutes-since-midnight — VERIFIED :1293), `lo3`, `s` |
| `"break"` | break out of loop | — |
| `"exit"` | exit piston | `lo`: exit value operand |

Compile-target notes for these live in COMPILER_DECISIONS_HOLDING.md §E (re-keyed to these names at the v2 compiler spec).

## 3. Conditions (VERIFIED editCondition init :1570–1590, save :1650–1680)

Two node kinds, distinguished by `t`:

**`"condition"`** — a comparison:
```
{
  "t": "condition",
  "lo": <operand>,             // left (what's measured)
  "co": <comparison key>,      // operator — key into db.comparisons (served vocab)
  "ro": <operand>,             // right
  "ro2": <operand>,            // second right (for "between"-style comparisons)
  "to": <operand>,             // time/duration qualifier ("for at least X minutes")
  "to2": <operand>,            // second time qualifier
  "wd": <operand>, "wt": "l"|..., // only when "followed by" chaining: within-duration + option
  "ts": [ <task>, ... ],       // tasks to run when condition turns TRUE
  "fs": [ <task>, ... ],       // tasks to run when condition turns FALSE
  "z": "<description>",
  "sm": "auto"
}
```
`ts`/`fs` (true/false task lists) exist on every condition (VERIFIED init :1580–1581) — the compiler must honor them; they are easy to miss.

**`"group"`** — nested boolean group:
```
{ "t": "group", "c": [ <condition|group>, ... ], "o": "and"|"or"|"xor"|..., "n": <negate>, "wd"/"wt" when followed-by }
```

**Trigger vs. condition — RESOLVED, and it is BOTH a vocab property and a stored field.**
The comparison key's nature comes from which vocab bucket it lives in
(`comparisons.conditions{}` vs `comparisons.triggers{}` — see §10.2). But the **saved piston
also records the answer on the node itself** (VERIFIED-CAPTURE, 84-piston production corpus,
2026-07-12):
- `"ct"`: `"c"` (condition) or `"t"` (trigger) — the engine's classification of this node,
  written at save.
- `"s"`: boolean — whether this condition is **subscribed** (i.e. actually drives event
  subscriptions). Present on trigger-bearing nodes; the piston root's `subscriptions`
  counts in the `piston/get` response (SHIM_API_SPEC §4.5) tally these.
**Compiler consequence:** trigger extraction can read `ct`/`s` straight off the node rather
than re-deriving it from the comparisons vocab. Treat the vocab bucket as the authority for
*authoring* and `ct`/`s` as the authority for *compiling a saved piston*; if they ever
disagree, the vocab wins (the node fields are engine output and may be stale on an
imported/AI-authored piston that was never saved through a real engine — in that case the
compiler must derive them itself).

## 4. Operands (VERIFIED renderOperand switch :3686–3830, picker cases :4116–4136)

The universal value holder. Shape: `{ "t": "<kind>", ...kind fields }`. Editor-initialized empty operand carries all keys (`{t,d:[],a,g,v,c,x,e}` — VERIFIED :1577); only the kind's fields are meaningful.

**`f` field (VERIFIED-CAPTURE, real saved piston, 2026-07-12):** operands also carry an
`f` field (observed value `"l"`) not previously documented here — present on `"p"`/`"c"`
operands in a live capture. Purpose TO VERIFY (possibly a formatting/locale flag — `"l"`
suggests "literal" or "local"), but its presence is confirmed real, not a shim artifact —
pass it through verbatim regardless of what it turns out to mean.

**Device references can be a bare name, not just hashed ids (VERIFIED-CAPTURE, 2026-07-12):**
a `d` array (on a `"p"` operand or a statement's own `d`) can hold a **local variable name**
or **global name** (`@Name`) as a bare string instead of a hashed device id — e.g.
`lo.d: ["Light"]` (a local device-type variable named "Light") or an action's
`d: ["@Announce"]` (a device-type global). The actual hashed ids live only inside that
variable's/global's own definition (`piston.v[].v.d`, or `globals.json`'s `@Name.v`) — see
COMPILER_DECISIONS_HOLDING.md §H1 for why this matters (device-global edits never touch
piston JSON). PISTON_JSON_REFERENCE.md's compiler/importer consumers must resolve a `d`
array entry as "hashed id, or else a variable/global name to look up" — never assume it's
always already a hash.

| `t` | Kind | Fields |
|---|---|---|
| `"p"` | physical device attribute | `d`: [device ids **or bare variable/global names**, see above], `a`: attribute key, `i`: [sub-device indexes] (buttons etc., when attribute has sub-devices), `g`: aggregation `"any"/"all"/"least"/"most"/avg/min/max/sum/...` (required when `d.length > 1`), `p`: interaction `"a"|"p"|"s"` (any/physically/programmatically — VERIFIED :4248), `dm`/`dn`: capture matching/non-matching devices into the named local device variable (condition "advanced" feature; VERIFIED 2026-07-15 — editor writes them, piston.module.html:1400, engine reads them, webcore-piston.groovy:7793-7800; tipped off by the dashboard-next wire map. Engine side effect at :7797-7799: requesting either one — same as any timed trigger — forces the condition group to evaluate ALL members, disabling short-circuit optimization. 0/84 corpus pistons use them — test priority only; compiler IMPLEMENTS them (populate the named variable with the matching/non-matching device lists during condition evaluation — COMPILER_SPEC §5 make-it-work rule), never silently ignores) |
| `"d"` | device list (for device-type contexts) | `d`: [device ids **or bare variable/global names**, see above] |
| `"v"` | virtual/system device | `v`: virtual device key (from instance.virtualDevices) |
| `"s"` | preset value | preset key (TO VERIFY exact field — dialog case :4128) |
| `"x"` | variable | `x`: variable name (string, `@Name` for globals, `$name` for system vars) or array of names (dynamic multi) |
| `"u"` | argument/dynamic | (used in expression argument contexts) |
| `"c"` | constant | `c`: the value, `vt`: value type. Encodings: time → **minutes since midnight** (int); date/datetime → **epoch ms** (VERIFIED fixOperand :1636–1647); `vt` confirmed present in live capture. |
| `"e"` | expression | `e`: expression source string. `exp` (the editor's cached parse) is **RESOLVED, VERIFIED-CAPTURE 2026-07-12: NOT stripped** — a real saved piston has `exp` present verbatim inside stored conditions/tasks. The shim's storage policy (store the piston JSON exactly as sent) means this was already effectively decided, and the capture confirms it holds in practice, not just by policy. |

## 5. Tasks (VERIFIED updateTask :2018–2045)

Used in `action.k`, `condition.ts`, `condition.fs`:
```
{
  "c":  "<command key>",        // key into db.commands (physical or virtual)
  "p":  [ <operand>, ... ],     // parameters, in the command's declared order (constants get time/date encoding per §4 "c")
  "a":  <async flag>,
  "m":  <mode>,                 // TO VERIFY value set
  "cm": <custom command info>,  // when command was entered as custom ($custom prefix stripped — VERIFIED :2021)
  "z":  "<description>"
}
```

## 6. Switch cases (VERIFIED updateCase :1425–1450)

```
{ "t": "<case type>", "ro": <operand>, "ro2": <operand>, "s": [ <statement>, ... ], "z": "" }
```
`ro2` for range cases; default branch is the parent switch's `e`, not a case.

## 7. Restrictions (VERIFIED updateRestriction :1856–1885)

Same comparison anatomy as conditions, different node names:
- `{ "t": "restriction", "lo", "co", "ro", "ro2", "to", "to2", "z" }`
- `{ "t": "group", "r": [ ... ], "rop": "and"|..., "rn": <negate> }`
Appear in piston root `r` and statement-level `r`.

## 8. Node IDs and trace

Stock webCoRE nodes carry a small integer `$` id used by the trace/status view to key highlights and by logs. The editor source does not assign them — the **engine** normalizes/assigns at save. **VERIFIED-HE-GROOVY** (2026-07-10, `webcore-piston.groovy:1412-1475`, `msetIds()`): recursively walks the piston tree; for every statement/condition/restriction/group/event node (and, specially, `if`'s `ei` else-if entries, `switch`'s `cs` case entries, and `action`'s `k` task entries), a node **keeps its existing `$` id** if it has one AND that id doesn't collide with an id already seen elsewhere in the tree; otherwise it's queued for a new id. After the full walk, every queued node gets `$` = `(max id seen) + 1`, incrementing per node, assigned in tree-traversal order. Confirms the V2 NOTE's assumption exactly, plus one nuance not previously documented: a **duplicate** `$` id (two nodes sharing one value, e.g. from a bad copy/paste) is NOT left alone — the second occurrence gets reassigned same as a missing id, so ids stay unique even if the input wasn't. A companion `clearMsetIds()` recursively nulls every `$` in a subtree (used when duplicating a piston, so the clone gets fresh ids rather than colliding with the original's). **V2 NOTE:** the shim implements this same rule on save (assign incremental `$` ids to nodes missing one or colliding with another, never renumber a valid existing one).

## 8b. Findings from the production corpus (VERIFIED-CAPTURE, 84 pistons, 2026-07-12)

A full webCoRE backup of Jeremy's live Hubitat install (84 pistons, scrubbed and stored in
`test-pistons/`) was decrypted and mined. It is the compiler's **requirements set**: what a
real eight-year webCoRE library actually uses. Everything below is observed in real saved
pistons, not inferred.

**Statement/node types actually used:** `if`, `action`, `each`, `while`, `repeat`, `do`,
`group`, `condition` + the operand kinds (`p`, `c`, `d`, `v`, `x`, `e`, `u`, `s`). Not
observed: `for`, `switch`, `on`, `break`, `exit` — documented in §2.2 but absent from this
corpus, so they are lower-priority compiler targets (still spec'd; just not corpus-proven).

**Comparisons used (22):** `is`, `is_not`, `is_any_of`, `is_between`, `is_not_between`,
`is_greater_than`, `is_greater_than_or_equal_to`, `is_less_than`,
`is_less_than_or_equal_to`, `changes`, `changes_to`, `changes_to_any_of`,
`changes_away_from`, `stays_any_of`, `stays_greater_than`,
`stays_greater_than_or_equal_to`, `stays_less_than`, `was`,
`was_greater_than_or_equal_to`, `happens_daily_at`, `executes`, `gets`.
The `stays_*` and `was_*` families are the hard ones for HA (they need duration/history
semantics — `for:` on triggers, or PyScript); `happens_daily_at` is a time trigger.

**Commands used (~70)**, notable groups: HSM (`setAlarmSystemStatus`), speech
(`speak`, `playText`, `playTextAndRestore`, `playTextAndResume`, `playTrack`,
`playTrackAndRestore`, `playSound`, `setVolume`, `stop`), lighting (`on`, `off`, `toggle`,
`setColor`, `setColorTemperature`, `fadeLevel`, `flash`, `startColorLoop`, `stopColorLoop`,
`stopColorTemperatureChange`), locks (`lock`), notification (`deviceNotification`,
`sendNotification`, `sendPushNotification`), virtual/control (`setVariable`, `wait`,
`cancelTasks`, `log`), camera (`take`, `clearImages`, `selectLiveview`).

**System variables actually referenced (12):** `$currentEventDescription`,
`$currentEventDevice`, `$device`, `$hsmStatus`, `$now`, `$time`, `$day`, `$monthName`,
`$sunrise`, `$sunset`, `$nextSunrise`, `$nextSunset`. **V2 NOTE:** the shim's systemVars
fixture (SHIM_API_SPEC §4.5) needs at minimum these; values that are dynamic (`$now`,
`$time`, sun times) must be served live from HA/clock, not hardcoded.

**`each` loops iterate either form:** a local device variable (`lo: {t:'d', d:["Door_Locks"]}`)
or a device global (`lo: {t:'x', x:["@Door_Contacts_Exterior"]}`). Inside the loop body,
`$device` is the current item — used as a bare `d` entry (`d: ["$device"]`) in both operands
and action targets. The compiler must bind `$device` per-iteration.

**Nested expression with device-attribute access:** `{([ $currentEventDevice : lastCodeName ])}`
— an expression node of `t:"device"` carrying `x` (the device ref) and `a` (attribute name),
nested inside `exp.i[]`. Compiler must support reading an arbitrary attribute off a
runtime-resolved device, not just off a picked one.

**Corpus use (V2 NOTE):** compile-all-84 is the compiler's regression suite and progress
metric. Work the small single-feature test pistons first (they isolate one construct each),
then mid-size, then the three ~80-node alarm pistons as the graduation exam.

## 9. AI-authoring guidance (the point of this doc)

To generate a valid piston: produce the root object (§1) with statements from §2.2, conditions §3, operands §4, tasks §5. Rules of thumb:
- Every capability/attribute/command/comparison key must exist in the served db (webcore_vocab-derived — SHIM_API_SPEC §4.4). Invalid keys render as broken nodes, not errors.
- Device references must be hashed IDs from the target install's device payload, OR a bare local-variable/global name (§4) whose own definition holds the hashed ids; for portable/shareable pistons prefer device-type **variables**, letting the importer bind devices once.
- Include the empty-but-expected arrays (`s`, `c`, `ei`, `e`, `ts`, `fs` per type) — the editor initializes them and TO VERIFY how it tolerates their absence; safest is to emit them.
- Times are minutes-since-midnight; dates are epoch ms; booleans in variables are `"false"`/`"true"` strings in option lists.

## 10. Open items
1. `o` (piston options) key meanings — enumerate from dashboard settings dialog / Groovy when a consumer needs them.
2. ~~Comparison vocab: which field marks trigger-type comparisons~~ — RESOLVED (2026-07-10,
   VERIFIED-HE-GROOVY `webcore.groovy:5645-5690`): not a field at all — `comparisonsFLD` is
   split into two top-level buckets, `comparisons.conditions{}` and `comparisons.triggers{}`.
   A comparison key's trigger-vs-condition status is which bucket it lives in, not a marker
   on the entry. `webcore_vocab.json` already has this structure correctly (confirmed
   matching, no fix needed).
3. tcp/tep/tsp/ctp/sm value sets — enumerate from piston.module.html dialogs at compiler time.
4. ~~`$` id assignment rule~~ — RESOLVED, see §8.
5. Preset operand (`t:"s"`) field name; task `m` value set. ~~Whether `exp` caches are
   stripped server-side~~ — RESOLVED, see §4 ("e" row): confirmed NOT stripped, stored
   verbatim (VERIFIED-CAPTURE 2026-07-12).
6. Statement types documented but NOT in the corpus (`for`, `switch`, `on`, `break`,
   `exit`) still need at least one hand-built capture each to validate §2.2 — build them in
   the editor and save (they are the remaining gaps in the acceptance test).
7. Validate this doc end-to-end during the spike: build one piston of each statement type in the running dashboard, save through the shim, diff the captured JSON against this reference, and promote/correct accordingly. **This is the doc's acceptance test.**
