# OpenCode Deprecation Scanner — Reference Extract

**Purpose:** External reference source for PistonCore's pre-deployment validation
strategy, extracted the same way the Hubitat webCoRE Groovy files are used — as an
upstream *reference*, not as code to import. This documents a proven pattern-catalog
schema and an auto-update mechanism we can adopt for catching HA deprecations
(including the 2026.7 trigger/condition renames PistonCore is tracking).

**Standing rule applied:** every claim below carries a verification status + source.

---

## Source provenance

- **Repo:** `magnusoverli/opencode` (HA add-on wrapping the OpenCode AI coding agent)
- **License:** Unlicense / public domain — free to copy, modify, compile, or lift
  outright. *Verified — UNLICENSE file, repo root, 2026-07-20.*
- **Reference tier:** Treat as PEER reference to the Hubitat Groovy sources — an
  external project that solved a problem we also face. NOT authority over PistonCore
  spec docs. Our COMPILER_DECISIONS_HOLDING.md and webcore_vocab.json remain law.
- **Files of interest (paths within repo, for re-pull if needed):**
  - `ha_opencode/rootfs/opt/shared/deprecation-patterns.json` — the pattern catalog
  - `ha_opencode/rootfs/opt/ha-mcp-server/index.js` — load / fetch / apply logic
    (lines ~1383–1460 cover load + remote fetch)
- **Re-pull command (codeload is an allowed egress domain):**
  ```
  curl -sL "https://codeload.github.com/magnusoverli/opencode/tar.gz/refs/heads/main" -o opencode.tar.gz
  ```

---

## What this is (and what it is NOT)

- **IS:** a JSON catalog of regex patterns that flag deprecated/legacy HA YAML syntax,
  plus a JS loader that compiles them to regexes and applies them to config text
  before a write is committed. *Verified — deprecation-patterns.json + index.js,
  2026-07-20.*
- **IS NOT:** a piston→YAML compiler. OpenCode has no deterministic compile path; the
  actual YAML is generated live by whatever LLM the user connects. This scanner only
  *checks* text after the fact. PistonCore's deterministic compiler is the thing
  OpenCode lacks — this scanner does not compete with it. *Verified — repo README +
  index.js write-tool description, 2026-07-20.*

**Bottom line for PistonCore:** we adopt the *schema and mechanism*, not their patterns.
Their newest pattern is dated 2024.6 — none of the 20 cover the 2026.7 trigger/condition
renames we track in HA_LIMITATIONS.md. We author those ourselves into this format.

---

## Pattern schema (the reusable artifact)

Each catalog entry is a flat JSON object. *Verified — deprecation-patterns.json,
2026-07-20:*

```json
{
  "id": "entity-id-in-data",
  "pattern": "data:\\s*\\n\\s*entity_id:",
  "flags": "m",
  "message": "Placing entity_id inside 'data:' is deprecated for service calls. Use 'target:' instead.",
  "suggestion": "Move entity_id from data: to target:\n  target:\n    entity_id: light.example",
  "deprecated_in": "2021.11",
  "severity": "warning"
}
```

Field semantics:

- `id` — stable kebab-case identifier for the rule.
- `pattern` — JS regex source (string, double-escaped for JSON). Applied to raw YAML text.
- `flags` — regex flags; every current entry uses `"m"` (multiline). Defaults to `"m"`.
- `message` — human-readable explanation of the deprecation.
- `suggestion` — corrected syntax shown to the user/agent.
- `integration` — optional; the HA integration involved (e.g. `template`, `mqtt`).
- `deprecated_in` — optional; HA version the deprecation landed (e.g. `2024.1`).
- `severity` — `warning` (real deprecation) or `info` (style/best-practice nudge).

**PistonCore adoption note:** this is text-regex matching against emitted YAML, which
fits our validation layer cleanly — we run it on compiler output *before* the
`ha core check` API call, as a cheap first gate. It does not require a running HA.

---

## The 20 upstream patterns (inventory)

*Verified — deprecation-patterns.json (20 entries total), 2026-07-20.*

| id | severity | deprecated_in |
|---|---|---|
| template-sensor-legacy | warning | 2024.1 |
| template-binary-sensor-legacy | warning | 2024.1 |
| entity-namespace-deprecated | warning | 2023.8 |
| time-date-platform-deprecated | warning | 2024.6 |
| automation-missing-id | info | — |
| legacy-device-tracker | info | — |
| template-cover-legacy | warning | 2024.1 |
| template-switch-legacy | warning | 2024.4 |
| customize-yaml-info | info | — |
| white-value-deprecated | warning | 2023.3 |
| direct-state-object-access | warning | — |
| direct-attribute-object-access | warning | — |
| value-template-legacy-key | info | — |
| mqtt-sensor-legacy-platform | warning | 2022.12 |
| mqtt-binary-sensor-legacy | warning | 2022.12 |
| mqtt-switch-legacy | warning | 2022.12 |
| mqtt-light-legacy | warning | 2022.12 |
| for-string-format | info | — |
| entity-id-in-data | warning | 2021.11 |
| hassio-service-renamed | warning | — |

**Directly relevant to PistonCore compiler output** (things our emitter must NOT produce):
- `entity-id-in-data` — use `target:` not `data: entity_id:`. Our YAML emitter should
  already target correctly; this pattern is a good regression guard. *Decision — add to
  our validation set.*
- `for-string-format` — dict form for `for:` durations, not `"0:05:00"` strings.
  Relevant to timer/duration compilation. *Decision — add as a self-check.*
- `direct-state-object-access` / `direct-attribute-object-access` — prefer
  `states('...')` / `state_attr('...')` over `states.x.y.state`. Relevant if any
  template output paths emit direct object access. *Assumed relevant — needs review
  against our Jinja emit paths.*

---

## Auto-update mechanism

*Verified — index.js lines ~1383–1460, 2026-07-20.*

Two-tier: local bundled copy is authoritative fallback; a remote fetch layers newer
patterns on top between releases.

1. **Local load** (`loadLocalDeprecationPatterns`): reads the bundled JSON, compiles
   each `pattern` string to `new RegExp(p.pattern, p.flags || "m")`. On any error,
   returns `[]` and logs a warning — never throws.
2. **Remote fetch** (`fetchRemoteDeprecationPatterns`): pulls the same file from
   `raw.githubusercontent.com/magnusoverli/opencode/main/.../deprecation-patterns.json`,
   validates it's a non-empty array, compiles it. Falls back to local on any failure.
3. **Caching:** in-memory with a 1-hour TTL (`DYNAMIC_CACHE_TTL = 3600000`) and a
   10-minute failure back-off (`DYNAMIC_CACHE_RETRY_TTL = 600000`) so offline installs
   don't eat a 5s fetch timeout every call. Fetch uses `AbortSignal.timeout(5000)`.

**Reality check on "auto-updated from GitHub":** it's a raw-file GET against `main`
with a 1-hour cache — not a curated/versioned feed. Effective, but modest. For
PistonCore we'd point the same mechanism at *our own* pattern file in
`jercoates/pistoncore-v2` rather than depending on their repo. *Decision — self-host
the pattern file; do not fetch theirs at runtime.*

---

## Bonus source discovered: HA official alerts feed

*Verified — index.js line 1411 (`HA_ALERTS_URL`), 2026-07-20.*

OpenCode also consumes Home Assistant's **official** public alerts feed:

```
https://alerts.home-assistant.io/alerts.json
```

Public, no auth, contains known integration issues with version ranges. This is a
first-party HA source (not OpenCode's) and is independently useful to PistonCore for
surfacing integration-level breakage tied to HA versions. *Assumed useful — needs a
look at the JSON shape before we commit to consuming it.*

**Why this matters more than the scanner for one specific risk — retired primitives:**
PistonCore's whole compile strategy rests on "emit classic primitives only" because
classic primitives are assumed stable. If HA ever actually *retires* a classic
primitive, that assumption breaks and every compiled piston starts emitting something
HA no longer accepts. The deprecation scanner CANNOT warn about this in time — it only
matches syntax already present in a file, so by the time it could flag a retired
primitive we'd already have emitted it (post-mortem, not pre-emptive). The alerts feed
is the correct early-warning mechanism: it's HA telling us directly, with version
ranges, that something changed — before it bites. *Decision — treat the alerts feed as
the "primitives-retirement watch," a separate mechanism from the scanner.*

---

## Three roles, three mechanisms — DO NOT collapse into one

*Decision — established this session, 2026-07-20.* The scanner, the alerts feed, and
the compiler each do a distinct job and fire on a distinct signal. Collapsing them
gives a false sense of coverage.

1. **Compiler = AUTHORITY (prevention).** Emits classic primitives only, keeps
   `target:` correct, never produces deprecated syntax. This is where correctness
   lives. Neither of the other two mechanisms ever edits compiler output. If the
   scanner ever fires on our own output, that is a COMPILER BUG — fix the template,
   not the output.

2. **Scanner = GATE (contamination + regression alarm).** Regex-matches deprecated
   syntax in any YAML file, blocks the deploy, and points at the offending line. It
   guards TWO boundaries:
   - **Our emitter** — regression guard; catches a template that regressed into
     non-primitive/deprecated syntax.
   - **User input** — contamination guard. PistonCore serves stock webCoRE and imports
     REAL pistons (community share codes, hand edits, old fixtures). Deprecated syntax
     can enter from the user side, not just ours. The scanner flags it regardless of
     origin so the user can fix their contaminated template/piston before deploy.

   **FLAG, NEVER REWRITE.** The scanner reports and blocks; it does not auto-correct.
   Auto-rewriting compiler output would make the compiler no longer the source of truth
   for what deploys, break spec-traceability, and eventually mangle a valid edge case
   silently (their `suggestion` fields are human hints, not mechanical transforms).
   Correct-on-the-fly is explicitly rejected. *Decision — flag-don't-rewrite.*

3. **Alerts feed = WATCH (foundation guard).** Periodically checks HA's first-party
   alerts feed for retirement/breakage of things we depend on — especially the classic
   primitives our whole strategy assumes are stable. Pre-emptive, not post-mortem.
   Warns us before the ground shifts; we (via Code) then fix the template or the
   strategy. See the alerts-feed section above.

**Why they can't merge:** they fail differently and fire on different signals. The
scanner can only ever be reactive (matches text already present); the alerts feed is
the only one that can warn *before* we emit a retired primitive. "The scanner also
warns about retired primitives" is false coverage — by the time it could match one,
we'd already have shipped it.

---

## Recommended PistonCore adoption (proposals, not decisions)

1. **Adopt the schema verbatim.** Create `pistoncore_deprecation_patterns.json` using
   the exact field set above. Data-driven, consistent with our "all rules data-driven"
   standing rule.
2. **Author the 2026.7 rename patterns ourselves.** The 8 trigger keys + 2 condition
   keys from HA_YAML_COMPILER_RESEARCH.md become the first PistonCore-specific entries.
   This is the gap the upstream catalog does not cover.
3. **Run as the cheap first gate** in the deploy validation chain, ahead of the
   `ha core check` API call and the dummy-helper test instance. Regex text-match needs
   no running HA.
4. **Self-host the pattern file** in pistoncore-v2; reuse their load/fetch/cache shape
   but point it at our repo. Do not fetch magnusoverli/opencode at runtime.
5. **Evaluate the HA alerts feed** as a separate, first-party signal.

---

## Open items / re-test flags

- [ ] Confirm none of our emitter paths trip `entity-id-in-data`,
      `direct-state-object-access`, or `for-string-format` (regression guards).
- [ ] Inspect `alerts.home-assistant.io/alerts.json` shape before consuming.
- [ ] Author 2026.7 trigger/condition rename patterns in this schema.
- [ ] Decide whether PyScript-emitted output needs its own pattern subset.
- [ ] Implement scanner as a FLAG-and-BLOCK gate (not a rewriter) covering both our
      emitter output and imported user pistons.
- [ ] Stand up the alerts feed as a separate primitives-retirement watch; define how
      often it's checked and how a hit surfaces to Jeremy.
