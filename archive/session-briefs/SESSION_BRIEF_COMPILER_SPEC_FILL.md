# SESSION BRIEF — Fill COMPILER_SPEC.md (spec sessions, no compiler code)

Rules: CLAUDE.md discipline. These are SPEC/RESEARCH sessions — no compiler implementation.
Multiple sessions expected; do them in the order below. Every claim tagged with source.

## Session A — Write the missing INTENT layer (the compiler's brain)

The skeleton jumps from "piston JSON" to "resolve/route/emit" as if meaning extraction were
free. It isn't — it's the core. Add a new **§2.5 Semantic model** and change the pipeline
to **ANALYZE → RESOLVE → ROUTE → EMIT → DEPLOY → LIFECYCLE**, then write both.

### §2.5 Semantic model — "how a piston means"
Document how webCoRE actually executes, because intent = what the user learned to expect
from that execution. Source: `reference/.../webcore-piston.groovy` (the engine — this
absorbs open-item 4's mining) + WEBCORE_HA_BEHAVIOR_MAP.md §1 + the webCoRE wiki semantics
already cited there. Cover, each with groovy line refs:
1. **The event loop:** a piston is dormant; `s:true` nodes define its subscriptions; an
   event wakes it; it evaluates top-to-bottom in ONE pass; triggers evaluate true only for
   the waking event's node, conditions read current state. THIS is the semantic root of
   trigger-vs-condition and must be stated as the baseline everything compiles against.
2. **Mixed if-blocks:** trigger + condition in one `if` = "when trigger fires AND condition
   currently holds" — maps to HA trigger + condition gate. No trigger at all in a piston =
   subscribes to every device state in conditions (webCOoRE's implicit-subscription rule —
   verify exact rule in groovy).
3. **Truth-change semantics:** `ts`/`fs` fire on condition EDGE (turns true / turns false),
   not on every evaluation; if-blocks similarly gate re-execution (cancel-on-condition-
   change ties in here). Get the exact rule — it decides whether compiled automations need
   edge detection or can rely on HA trigger semantics.
4. **TCP per statement:** what exactly gets cancelled when (`tcp` values from
   piston.module.html dialogs — enumerate the value set), how scheduled tasks are keyed.
   Then rule on the `mode: restart` candidate (DECIDED file §7 caution) with evidence.
5. **`a` async flag, `each` iteration order, `while/repeat` re-evaluation timing, `every`
   scheduling internals, exit semantics** — brief, per construct.
6. **Expression evaluation:** coercion rules, `$device`/system-var resolution timing.
   (Enough for the corpus's 12 system vars + observed expressions; not the whole language.)

### §3.0 ANALYZE stage
The pass that converts a piston tree into an intent structure BEFORE resolve/route:
- Extract subscriptions (`ct`/`s`, or derived) → the automation's trigger set.
- Classify each if/on block into one of the INTENT PATTERNS (write the pattern catalog —
  this is the key artifact): e.g. "trigger-gated action", "state-mirror" (if X on → Y on,
  else Y off), "timed follow-up with reset" (motion → wait N → off, TCP cancels),
  "edge announcement" (changes-to → speak/notify), "loop-over-devices", "schedule block"
  (every/happens_daily_at), "guard-only piston" (restrictions + no trigger). Derive the
  catalog FROM THE CORPUS: mine all 84 pistons, cluster their shapes, name each pattern,
  cite example pistons by filename. Every pattern gets: JSON signature → intended behavior
  in one sentence → target HA construct set (YAML and/or PyScript form).
- Unclassifiable structures fall back to statement-by-statement compilation (behavior map
  §1 pairings) — patterns are an optimization for fidelity/readability, not a gate.

## Session B — Fill the EMIT bands from the research docs (transcription)
- §3.3 YAML: import behavior-map §2 comparison table verbatim (mark corpus-22 must-pass);
  write the emission baseline from HA_YAML_COMPILER_RESEARCH §1; the nested if/ei/e →
  choose mapping from behavior map §1 + §G output sketches; restrictions mapping.
- §3.3 PyScript: per-construct snippet list from PYSCRIPT_COMPILER_RESEARCH §2–§8.
- §3.2 routing: complete the re-key of holding doc §E rows to PISTON_JSON_REFERENCE field
  signatures; define the stays/was native-vs-PyScript boundary from behavior map §2 +
  HA_LIMITATIONS §2.
- §3.1: the global-inlining table from holding doc C-TYPES.
- Execute both research docs' §5 port-back lists while in there.

## Session C — Reconciliation + fixtures
- Reconcile WEBCORE_HA_BEHAVIOR_MAP §6 against the routing table (four "cut" items are
  actually PyScript-routed); split into truly-unmappable vs routed; update §5 of the spec.
- Golden fixtures: for each intent pattern from Session A, pick one corpus piston (or the
  Test 1 capture) and hand-write its EXPECTED YAML/PyScript output as a fixture file —
  Jeremy reviews these behaviorally ("is this what that piston should do?"). These become
  §6's acceptance set before any compiler code exists.

## End of each session
Plain-language summary; updated spec committed; new TO VERIFYs listed rather than guessed.
