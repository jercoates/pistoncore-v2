<!-- PROVENANCE (PistonCore, 2026-07-15): copied read-only from Jeremy's
dashboard-next repo (C:/Users/Jeremy/Documents/GitHub/weBcoRE/dashboard-next/ — a
Grok-built modern-Angular webCoRE clone, separate project, different architecture).
Generated from its mapper.ts/model.ts boundary layer; VALIDATED by real round-trips —
pistons saved by dashboard-next to Jeremy's spare Hubitat render correctly in the real
webCoRE dashboard (screenshots 2026-07-15). Cross-checked against pistoncore-v2's own
sources 2026-07-15: it confirmed `tsp` (taskSchedulingPolicy) and tipped off the dm/dn
operand fields (both then verified against piston.module.html:1400 +
webcore-piston.groovy:7793-7800 and added to PISTON_JSON_REFERENCE.md §4).
AUTHORITY: corroborating reference ONLY — on any conflict, PISTON_JSON_REFERENCE.md and
the webCoRE sources win (CLAUDE.md authority chain). Its PISTON_PORT_AUDIT.md companion
is INVALID (confirmed by Jeremy 2026-07-15) — do not chase that cross-reference. -->

# webCoRE Piston JSON — Wire Format ↔ Readable Model Cross-Reference

Generated from `dashboard-next`'s TypeScript boundary layer:
- `src/app/core/piston/model.ts` — the readable shape the Angular app works with
- `src/app/core/piston/mapper.ts` — the ONLY code allowed to know the single-letter
  wire keys; every conversion below is taken directly from its `fromLegacy*`/
  `toLegacy*` function pairs, not inferred.

This describes the actual JSON a piston is stored/transmitted as (what the hub's
`piston/get` API returns in its `data.piston` / `code` field, and what gets sent
back on save) — the same format `piston.module.js` reads and writes natively.

---

## 1. How to read this

Every section below is a table: **wire key** (the literal JSON property name) →
**readable name** (what `dashboard-next` calls it) → **type / meaning**. Nesting
follows the JSON structure — e.g. a statement's `s` key holds an array of more
statement objects, recursively.

Two important behaviors baked into `dashboard-next`'s encoder/decoder, worth
replicating in any independent implementation (like pistoncore) that wants to
round-trip real piston JSON byte-for-byte:

- **Unknown keys are preserved verbatim.** If a real piston contains a wire key
  not in these tables, `dashboard-next` stores it in an internal bag and writes
  it back out unchanged on save, rather than dropping it. Several keys observed
  in production data are explicitly *not* fully understood yet (flagged below)
  and are passed through rather than guessed at.
- **Absent ≠ empty.** At the piston root, a key that was never present on load
  (e.g. a hand-built/programmatic piston with no `v` key at all) is not written
  back out as an empty array — the encoder only emits root keys that existed on
  the way in. An empty `{}` piston round-trips to `{}`, not to a skeleton with
  empty `o`/`r`/`s`/`v`.

---

## 2. Root piston document

The top-level object (`data.piston` from `piston/get`, or the `code`/piston body
elsewhere):

| Wire key | Readable name | Type | Notes |
|---|---|---|---|
| `id` | `id` | string | Engine-assigned id, not always present |
| `o` | `options` | object | See §3 |
| `r` | `restrictions` | array | See §5 |
| `rop` | `restrictionOperator` | string (`and`/`or`/`xor`) | Root-level restriction grouping operator |
| `rn` | `restrictionsNegated` | boolean | Root-level restriction negation |
| `s` | `statements` | array | See §6 |
| `v` | `variables` | array | See §4 |
| `z` | `description` | string | Same `z`-for-description convention used everywhere else in the format |
| *(anything else)* | — | — | Preserved verbatim, unparsed. `l` has been observed as an empty object on some saves; meaning not confirmed |

---

## 3. Options block (`o`)

Engine/designer flags, nested one level under the root's `o` key. Field names
below match the editor's own internal flag names (`piston.module.js` ~1043–1072).

| Wire key | Readable name | Type |
|---|---|---|
| `mps` | `disableAutomaticPistonState` | number/boolean (truthy = disabled) |
| `dco` | `disableCommandOptimization` | number/boolean |
| `cto` | `disableConditionTraversalOptimizations` | number/boolean |
| `pep` | `enableParallelism` | number/boolean |
| `des` | `disableEventSubscriptions` | number/boolean |
| `aps` | `allowPreScheduledTasksDuringRestrictions` | number/boolean |
| `ced` | `commandExecutionDelayMs` | number (milliseconds) |
| `ish` | `ignoreSslErrors` | number/boolean |

Any other key under `o` is passed through unmodified.

---

## 4. Local variables (`v[]`)

Each entry:

| Wire key | Readable name | Type | Notes |
|---|---|---|---|
| `n` | `name` | string | Sanitized to `[a-z0-9_]` on save (spaces/newlines/other chars → `_`) |
| `t` | `type` | string | e.g. `dynamic`, `decimal`, `string`, `boolean`, `device`, … |
| `a` | `access` | string | Observed value `"d"` for device-typed vars; full meaning not confirmed |
| `v` | `value` | scalar, or nested operand-shaped object | If the value object looks like an operand (has its own `t` key), it's decoded via the operand rules in §11; otherwise passed through as-is |
| `z` | `description` | string | Same convention as everywhere else |

---

## 5. Restrictions (`r[]`)

A restriction list entry is either a single comparison or a group; distinguished
by its `t` key (`"group"` vs. anything else, conventionally `"restriction"`).

**Restriction comparison:**

| Wire key | Readable name | Type |
|---|---|---|
| `$` | `nodeId` | number |
| `lo` | `leftOperand` | operand (§11) |
| `co` | `comparison` | string (operator id) |
| `ro` | `rightOperand` | operand |
| `ro2` | `rightOperand2` | operand |
| `to` | `timeOperand` | operand |
| `to2` | `timeOperand2` | operand |
| `z` | `description` | string |

Note: restrictions never carry `ts`/`fs` (true/false statement lists) or a
subscription-mode field — those are condition-only concepts.

**Restriction group** (`t: "group"`):

| Wire key | Readable name | Type |
|---|---|---|
| `$` | `nodeId` | number |
| `r` | `restrictions` | array (recursive — more restriction nodes) |
| `rop` | `restrictionOperator` | string (`and`/`or`/`xor`/`followed by`) |
| `rn` | `restrictionsNegated` | boolean |
| `z` | `description` | string |

---

## 6. Statements (`s[]`)

Every statement shares a base set of fields, plus type-specific fields keyed off
its `t` value.

**Base fields (all statement types):**

| Wire key | Readable name | Type |
|---|---|---|
| `t` | `statementType` | string — one of `action`,`do`,`on`,`if`,`switch`,`for`,`each`,`while`,`repeat`,`every`,`break`,`exit` (unrecognized values pass through as a generic statement, not dropped) |
| `$` | `nodeId` | number |
| `a` | `async` | string/boolean/number — often the literal string `"0"`/`"1"` |
| `di` | `disabled` | boolean |
| `tcp` | `taskCancellationPolicy` | string (policy code, opaque) |
| `tep` | `taskExecutionPolicy` | string |
| `tsp` | `taskSchedulingPolicy` | string |
| `ctp` | `caseTraversalPolicy` | string (only meaningful on `switch`, but modeled at base level) |
| `sm` | `statementMode` | string — omitted entirely on wire when value is `"auto"` |
| `z` | `description` | string |
| `w` | `warnings` | array of strings — engine-generated validation warnings |
| `rop` | `restrictionOperator` | string — per-statement restriction operator |
| `rn` | `restrictionsNegated` | boolean |
| `r` | `restrictions` | array — per-statement restriction list (same shape as §5) |

**Type-specific fields**, added on top of the base:

| Type | Wire key | Readable name | Type |
|---|---|---|---|
| `action` | `d` | `devices` | array of strings (device ids, `$device`, local var names, or `@global`) |
| `action` | `k` | `tasks` | array — see §13 |
| `do` | `s` | `statements` | array (recursive) |
| `on` | `c` | `conditions` | array — see §10 |
| `on` | `o` | `operator` | string — always `or` on wire |
| `on` | `n` | `negate` | boolean |
| `on` | `s` | `statements` | array |
| `if` | `o` | `operator` | string |
| `if` | `n` | `negate` | boolean |
| `if` | `c` | `conditions` | array |
| `if` | `s` | `statements` | array — then-branch |
| `if` | `ei` | `elseIfs` | array — see §8 |
| `if` | `e` | `elseStatements` | array — else-branch |
| `switch` | `lo` | `leftOperand` | operand — the switch expression |
| `switch` | `cs` | `cases` | array — see §9 |
| `switch` | `e` | `elseStatements` | array — default/else branch |
| `switch` | `ctp` | `caseTraversalPolicy` | string (also listed at base — lives here functionally) |
| `for` | `x` | `loopVariable` | string |
| `for` | `lo` | `fromOperand` | operand |
| `for` | `lo2` | `toOperand` | operand |
| `for` | `lo3` | `stepOperand` | operand |
| `for` | `s` | `statements` | array — loop body |
| `each` | `x` | `loopVariable` | string |
| `each` | `lo` | `collectionOperand` | operand — device list to iterate |
| `each` | `s` | `statements` | array |
| `while` | `o` | `operator` | string |
| `while` | `n` | `negate` | boolean |
| `while` | `c` | `conditions` | array |
| `while` | `s` | `statements` | array |
| `repeat` | `o` | `operator` | string |
| `repeat` | `n` | `negate` | boolean |
| `repeat` | `c` | `conditions` | array |
| `repeat` | `s` | `statements` | array |
| `every` | `lo` | `intervalOperand` | operand — the recurrence interval |
| `every` | `lo2` | `timeAnchorOperand` | operand — anchor time-of-day (minutes since midnight when a constant) |
| `every` | `lo3` | `thirdOperand` | operand — offset, when time anchor isn't constant |
| `every` | `s` | `statements` | array |
| `break` | *(none)* | — | Genuinely no extra fields |
| `exit` | `lo` | `valueOperand` | operand — the new piston state string |

`while`/`repeat`/`on` share an identical shape; they're only distinguished by
their `t` value.

---

## 7. Else-if branches (`ei[]`, inside `if`)

| Wire key | Readable name | Type |
|---|---|---|
| `$` | `nodeId` | number |
| `o` | `operator` | string (defaults to `and` if absent) |
| `n` | `negate` | boolean |
| `c` | `conditions` | array |
| `s` | `statements` | array |

---

## 8. Switch cases (`cs[]`, inside `switch`)

| Wire key | Readable name | Type |
|---|---|---|
| `$` | `nodeId` | number |
| `t` | `caseType` | string — `s` (single value) or `r` (range) |
| `ro` | `rightOperand` | operand — the value to match |
| `ro2` | `rightOperand2` | operand — range upper bound, only when `caseType` is range |
| `s` | `statements` | array — this case's body |
| `z` | `description` | string |

---

## 9. Conditions (`c[]`, inside `if`/`on`/`while`/`repeat`/else-if branches)

Like restrictions, a condition list entry is either a comparison or a group,
keyed by `t` (`"group"` vs. `"condition"`).

**Condition comparison:**

| Wire key | Readable name | Type |
|---|---|---|
| `$` | `nodeId` | number |
| `lo` | `leftOperand` | operand |
| `co` | `comparison` | string (operator id) |
| `ro` | `rightOperand` | operand |
| `ro2` | `rightOperand2` | operand |
| `to` | `timeOperand` | operand — time-window offset |
| `to2` | `timeOperand2` | operand |
| `wd` | `withinDuration` | operand — "followed by, within N minutes" duration |
| `wt` | `withinOption` | string — matching method for the followed-by window |
| `ts` | `trueTasks` | array — statements/tasks that run when this condition is true ("when true") |
| `fs` | `falseTasks` | array — "when false" |
| `z` | `description` | string |
| `sm` | `statementMode` | string — subscription mode |
| `ct` | `classification` | string, decoded `c`→`condition`, `t`→`trigger` |
| `s` | `subscribed` | boolean — **note:** this is a different `s` than the statements-array `s` used elsewhere; here it's a flag, only meaningful when its value is literally boolean |

**`ts`/`fs` entries** can be either a bare task object (§13) or a full nested
statement (most commonly an `action` block) — distinguished by checking whether
the entry's `t` value matches one of the twelve statement-type strings; if not,
it's treated as a bare task.

**Condition group** (`t: "group"`):

| Wire key | Readable name | Type |
|---|---|---|
| `$` | `nodeId` | number |
| `c` | `children` | array (recursive) |
| `o` | `operator` | string (`and`/`or`/`xor`/`followed by`) |
| `n` | `negate` | boolean |
| `wd` | `withinDuration` | operand |
| `wt` | `withinOption` | string |
| `z` | `description` | string |

Note: the editor sometimes stamps empty `ts`/`fs`/`sm` values onto group nodes
even though they're not semantically meaningful there — these are preserved via
passthrough for round-trip fidelity but are not modeled as real group fields.

---

## 10. Operands — the universal value structure

Operands appear everywhere a "value" is needed: `lo`/`ro`/`ro2`/`to`/`to2`/`wd`
on conditions/restrictions, `lo`/`lo2`/`lo3` on statements, `ro`/`ro2` on switch
cases, each entry of a task's parameter array, and inside a device-typed local
variable's `v`.

The **outer `t` key selects the operand kind**, which then determines which of
the other keys are meaningful:

| `t` (wire) | Readable `operandType` | Meaning |
|---|---|---|
| `p` | `deviceAttribute` | A specific device + attribute (e.g. "Kitchen Light's switch state") |
| `d` | `deviceList` | A raw list of devices, no attribute |
| `v` | `virtualDevice` | A virtual/webCoRE-emulated device (location mode, IFTTT, LIFX, etc.) |
| `s` | `preset` | A named preset/color value |
| `x` | `variable` | A reference to a local/global/system variable |
| `u` | `argument` | A function/expression argument slot |
| `c` | `constant` | A literal value |
| `e` | `expression` | A formula/expression string |

Absence of the `t` key entirely (rather than an empty string) is meaningful on
some optional operand slots and is preserved distinctly — an encoder shouldn't
invent `t: ""` where the source had no `t` key at all.

**All possible sub-fields** (which ones are populated depends on `t`, per the
table above; the mapper always reads them opportunistically):

| Wire key | Readable name | Type | When relevant |
|---|---|---|---|
| `d` | `devices` | array of strings | `deviceAttribute` / `deviceList` |
| `a` | `attribute` | string | Only when `t === 'p'` — the attribute name (e.g. `switch`, `temperature`) |
| `i` | `indexes` | array of string/number | Sub-device indexes (e.g. which button on a multi-button device) |
| `g` | `aggregation` | string | `any`,`all`,`least`,`most`,`avg`,`min`,`max`,`sum`, etc. — how multiple devices' values combine |
| `p` | `interaction` | string, decoded `a`→`any`, `p`→`physical`, `s`→`programmatic` | Only when `t === 'p'` |
| `v` | `virtualDevice` | string | Only when `t === 'v'` |
| `s` | `preset` | any | Only when `t === 's'` |
| `x` | `variable` | string or array of strings | `t === 'x'` |
| `c` | `constant` | any | `t === 'c'` (also used as a fallback wrapper — a bare non-object operand value on wire is treated as `{operandType: 'constant', constant: <value>}`) |
| `e` | `expression` | string | `t === 'e'` |
| `exp` | `expressionTree` | nested object | Cached parse tree, see §11 below — can co-occur with constants, not just expressions |
| `vt` | `valueType` | string | Value-type hint (e.g. duration unit) |
| `f` | `format` | string | Observed value `"l"` in production data; exact meaning **not confirmed**, passed through |
| `dm` | `matchingDevicesVariable` | string | Condition "advanced" — capture matching devices into this variable |
| `dn` | `nonMatchingDevicesVariable` | string | Condition "advanced" — capture non-matching devices |

**⚠️ Overloaded letter warning:** the operand-kind code `p` (device attribute)
and the *interaction* sub-field's wire key `p` (holding `a`/`p`/`s`) and one of
that sub-field's own *values* (`p` = physical) are three unrelated uses of the
same letter in the same object. Don't conflate them.

### 10a. Expression tree (`exp`)

Cached parse result attached to constant/expression operands:

| Wire key | Readable name | Type |
|---|---|---|
| `t` | `type` | string |
| `i` | `items` | array of expression items (recursive shape below) |
| `str` | `source` | string — original source text |
| `ok` | `ok` | boolean — whether it parsed cleanly |

Each item in `i`:

| Wire key | Readable name | Type |
|---|---|---|
| `t` | `type` | string |
| `v` | `value` | any |
| `l` | `location` | string — source span, e.g. `"0:9"` |
| `ok` | `ok` | boolean |
| `x` | `deviceRef` | string or array of strings |
| `a` | `attribute` | string |
| `i` | `items` | array (recursive, for nested expression nodes) |

---

## 11. Tasks (`k[]`, inside `action` statements)

| Wire key | Readable name | Type |
|---|---|---|
| `$` | `nodeId` | number |
| `c` | `command` | string — command id from the device-command vocabulary |
| `p` | `parameters` | array of operands, in declared command-parameter order |
| `a` | `async` | string/boolean/number |
| `m` | `mode` | any |
| `cm` | `customCommand` | any — metadata for a non-standard/custom command |
| `z` | `description` | string |

---

## 12. Piston list-meta vs. get-meta — two *different* envelope shapes

These are **not part of the piston body** above — they're the metadata wrapper
returned by two different hub endpoints, and they use different key conventions
from each other (get-meta already uses full English words on the wire; list-meta
uses single letters like the piston body does).

**List view meta** (short keys):

| Wire key | Readable name | Type |
|---|---|---|
| `a` | `active` | boolean |
| `c` | `category` | number or string |
| `t` | `lastExecuted` | number (timestamp) |
| `m` | `modified` | number (timestamp) |
| `b` | `bin` | string |
| `n` | `nextSchedule` | number (timestamp) |
| `z` | `description` | string |
| `s` | `state` | object |
| `heCached` | `heCached` | boolean — already a full word on wire |

**`piston/get` meta** (already long keys — mapped 1:1, just re-exposed with
consistent naming, no letter decoding needed):

| Wire key | Readable name | Type |
|---|---|---|
| `id` | `id` | string |
| `author` | `author` | string |
| `name` | `name` | string — HTML stripped on read |
| `created` | `created` | number |
| `modified` | `modified` | number |
| `build` | `build` | number |
| `bin` | `bin` | string |
| `active` | `active` | boolean |
| `category` | `category` | number/string |

---

## 13. Context-dependent / overloaded wire letters — gotchas for an independent implementation

The format reuses short letters heavily; the *same* letter means different
things depending on which object you're inside. This is the single biggest
trap for writing an independent parser from scratch:

| Letter | Meaning at piston root | Meaning on a statement | Meaning on a condition/restriction | Meaning on an operand | Meaning on a task | Meaning on a variable | Meaning on list-meta |
|---|---|---|---|---|---|---|---|
| `t` | *(not used at root)* | statement type | node type (`condition`/`group`/`restriction`) | operand kind | *(not used)* | variable type | lastExecuted timestamp |
| `s` | statements array | child statements array | `subscribed` boolean (condition only) | preset value (only when `t==='s'`) | *(not used)* | *(not used)* | state object |
| `a` | *(not used)* | async flag | *(not used)* | attribute name (only when `t==='p'`) | async flag | access | active boolean |
| `n` | *(not used)* | negate boolean | negate boolean (group) | *(not used)* | *(not used)* | name | nextSchedule timestamp |
| `c` | *(not used)* | conditions array (on if/on/while/repeat) | children array (group only) | constant value | command id | *(not used)* | category |
| `v` | variables array | *(not used)* | *(not used)* | virtual device id (only when `t==='v'`) | *(not used)* | value | *(not used)* |
| `z` | description | description | description | *(not used)* | description | description | description |
| `p` | *(not used)* | *(not used)* | *(not used)* | interaction mode (only when `t==='p'`) | *(not used)* | *(not used)* | *(not used)* |
| `x` | *(not used)* | loop variable name (for/each) | *(not used)* | variable name/list | *(not used)* | *(not used)* | *(not used)* |

`z` is the one mercifully consistent letter — it means "description" absolutely
everywhere it appears.

---

## 14. What's still uncertain

A handful of observed wire keys are preserved by `dashboard-next` but their
exact semantics aren't fully confirmed (called out in code comments, not
guessed at):

- Operand `f` (`format`) — observed value `"l"` in production captures, exact meaning unconfirmed.
- Variable `a` (`access`) — observed `"d"` for device-typed variables; full value space unconfirmed.
- Root-level `l` — observed as an empty object on some saves; purpose unknown.

If pistoncore's own corpus has resolved any of these, that'd be worth feeding
back into `dashboard-next`'s `model.ts`/`mapper.ts` comments too.

---

*Source authority for this document: `dashboard-next/src/app/core/piston/model.ts`
and `mapper.ts`, cross-checked against `webCoRE-master/dashboard/js/modules/piston.module.js`
during the piston-editor port audit (see `PISTON_PORT_AUDIT.md` in this same repo).*
