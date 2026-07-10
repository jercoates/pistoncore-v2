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

Trigger vs. condition is NOT a structural flag on the node — it is a property of the chosen comparison (`co`): db.comparisons entries are divided into condition-comparisons ("is", "is less than") and trigger-comparisons ("changes to", "stays"). TO VERIFY the db field that marks a comparison as a trigger (expected in the comparisons vocab); the compiler's trigger extraction hangs on it.

## 4. Operands (VERIFIED renderOperand switch :3686–3830, picker cases :4116–4136)

The universal value holder. Shape: `{ "t": "<kind>", ...kind fields }`. Editor-initialized empty operand carries all keys (`{t,d:[],a,g,v,c,x,e}` — VERIFIED :1577); only the kind's fields are meaningful.

| `t` | Kind | Fields |
|---|---|---|
| `"p"` | physical device attribute | `d`: [device ids], `a`: attribute key, `i`: [sub-device indexes] (buttons etc., when attribute has sub-devices), `g`: aggregation `"any"/"all"/"least"/"most"/avg/min/max/sum/...` (required when `d.length > 1`), `p`: interaction `"a"|"p"|"s"` (any/physically/programmatically — VERIFIED :4248) |
| `"d"` | device list (for device-type contexts) | `d`: [device ids] |
| `"v"` | virtual/system device | `v`: virtual device key (from instance.virtualDevices) |
| `"s"` | preset value | preset key (TO VERIFY exact field — dialog case :4128) |
| `"x"` | variable | `x`: variable name (string, `@Name` for globals, `$name` for system vars) or array of names (dynamic multi) |
| `"u"` | argument/dynamic | (used in expression argument contexts) |
| `"c"` | constant | `c`: the value, `vt`: value type. Encodings: time → **minutes since midnight** (int); date/datetime → **epoch ms** (VERIFIED fixOperand :1636–1647) |
| `"e"` | expression | `e`: expression source string (editor caches parse as `exp` — treated as derived, TO VERIFY whether engine strips it) |

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

Stock webCoRE nodes carry a small integer `$` id used by the trace/status view to key highlights and by logs. The editor source does not assign them — the **engine** normalizes/assigns at save (`piston.setup()`). TO VERIFY the exact assignment rule. **V2 NOTE:** the shim takes over this job — on save, walk the piston and assign incremental `$` ids to nodes missing one (never renumber existing ones, or trace keys and saved references drift). Until the trace feature exists this is low-stakes, but assign from day one so pistons don't churn ids later.

## 9. AI-authoring guidance (the point of this doc)

To generate a valid piston: produce the root object (§1) with statements from §2.2, conditions §3, operands §4, tasks §5. Rules of thumb:
- Every capability/attribute/command/comparison key must exist in the served db (webcore_vocab-derived — SHIM_API_SPEC §4.4). Invalid keys render as broken nodes, not errors.
- Device references must be hashed IDs from the target install's device payload; for portable/shareable pistons prefer device-type **variables** referenced via `x` operands, letting the importer bind devices once.
- Include the empty-but-expected arrays (`s`, `c`, `ei`, `e`, `ts`, `fs` per type) — the editor initializes them and TO VERIFY how it tolerates their absence; safest is to emit them.
- Times are minutes-since-midnight; dates are epoch ms; booleans in variables are `"false"`/`"true"` strings in option lists.

## 10. Open items
1. `o` (piston options) key meanings — enumerate from dashboard settings dialog / Groovy when a consumer needs them.
2. Comparison vocab: which field marks trigger-type comparisons (compiler's trigger extraction depends on it).
3. tcp/tep/tsp/ctp/sm value sets — enumerate from piston.module.html dialogs at compiler time.
4. `$` id assignment rule (engine-side) — define shim's rule per §8.
5. Preset operand (`t:"s"`) field name; task `m` value set; whether `exp` caches are stripped server-side.
6. Validate this doc end-to-end during the spike: build one piston of each statement type in the running dashboard, save through the shim, diff the captured JSON against this reference, and promote/correct accordingly. **This is the doc's acceptance test.**
