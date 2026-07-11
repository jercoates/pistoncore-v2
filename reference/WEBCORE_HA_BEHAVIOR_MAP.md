# WebCoRE → Home Assistant Behavioral Pairing Map
**Sources:** WebCoRE wiki (wiki.webcore.co), HA Automation Triggers docs (2026.6.3), HA Script Syntax docs (2026.6.3), HA Conditions docs (2026.6.3)  
**Purpose:** For each WebCoRE statement type and comparison operator, documents what it actually does and what HA construct produces equivalent behavior.  
**Method:** Verified from live docs — no assumptions. HA version confirmed 2026.6.3.

---

## Section 1 — Statement Type Behavioral Pairing

### 1.1 — `if` (If Block)

**What WebCoRE does:**  
Evaluates a set of conditions using the defined logical operator (AND/OR/XOR). If the result is true, executes the `then` statements. Supports optional `else if` branches (each with their own condition set) evaluated in order, and a final `else` branch. Supports nesting. Each condition can subscribe to device events independently.

**What HA has:**  
`if / then / else` action in script syntax (2026.5+). Conditions use HA condition types (`state`, `numeric_state`, `template`, `time`, `sun`, `zone`). Multiple conditions under `if` are AND-combined by default; OR/NOT require explicit logical condition wrappers.

```yaml
- if:
    - condition: state
      entity_id: binary_sensor.motion
      state: "on"
  then:
    - action: light.turn_on
      target:
        entity_id: light.hall
  else:
    - action: light.turn_off
      target:
        entity_id: light.hall
```

**Gaps vs WebCoRE:**
- HA `if` does not have `else if` natively — must be nested `if` inside `else`
- HA conditions are AND-only by default; XOR has no native equivalent (requires template)
- WebCoRE's "followed by" grouping (sequential event chaining) has no HA equivalent
- WebCoRE's per-condition event subscription has no HA equivalent — HA triggers are automation-level only
- WebCoRE's when-true/when-false inline statement blocks inside conditions have no HA equivalent

---

### 1.2 — `action` (With Block)

**What WebCoRE does:**  
Selects one or more devices and defines a list of tasks (commands) to execute against them. Tasks run sequentially within the block. Multiple devices in a single with-block receive all commands. Supports execution restrictions (only when modes match).

**What HA has:**  
`action:` in script/automation — calls a service against targets. No native "with block" grouping concept; each service call is its own action step. Multiple entities can be targeted in one call.

```yaml
- action: light.turn_on
  target:
    entity_id:
      - light.kitchen
      - light.living_room
  data:
    brightness_pct: 80
```

**Gaps vs WebCoRE:**
- No native grouping equivalent to the with-block; multiple commands to the same devices are simply sequential action steps
- WebCoRE's mode restriction filter (`only during these modes`) maps to a `condition` step before the actions, or inline condition in `choose`
- WebCoRE's Task Execution Policy (only on condition state change) has no HA equivalent in script syntax

---

### 1.3 — `do` (Do Block)

**What WebCoRE does:**  
Groups other statements together into a logical block for organizational purposes. No conditional logic — everything inside always runs. Useful for scoping restrictions.

**What HA has:**  
No direct equivalent. Functionally replaced by simply ordering actions sequentially. For grouping with a shared restriction, use `choose` with a single branch, or a `condition` action at the top of the group.

**Gaps vs WebCoRE:**  
Purely organizational — HA has no grouping construct without conditional logic attached.

---

### 1.4 — `on` (On Event)

**What WebCoRE does:**  
Subscribes to specific device attribute change events. When any of the listed events fires, executes the contained statements. Operates as a nested trigger — only triggers on the listed events regardless of what triggered the parent piston run. Multiple events are OR-combined (any one can fire it).

**What HA has:**  
No equivalent within a running automation/script. HA triggers are automation-level only — you cannot nest a trigger inside an action sequence. The closest approximation is `wait_for_trigger` in script syntax, which pauses execution until a specific trigger fires.

```yaml
- wait_for_trigger:
    - trigger: state
      entity_id: binary_sensor.door
      to: "on"
  timeout: "00:05:00"
  continue_on_timeout: false
```

**Gaps vs WebCoRE:**  
`wait_for_trigger` is a one-time wait, not a persistent subscription loop. For repeating "do X every time event Y happens," HA requires a separate automation. This is a fundamental architectural difference — WebCoRE pistons can be event-driven internally; HA automations are event-driven externally.

---

### 1.5 — `switch` (Switch)

**What WebCoRE does:**  
Evaluates an expression and compares it against a list of cases (single value or range). When a case matches, executes that case's statements. Two traversal policies: Safe (auto-break after first match) and Fall-through (continues to next case until break or end).

**What HA has:**  
`choose` action — evaluates a list of conditions in order and runs the first matching branch's sequence. Has a `default` branch. No concept of fall-through — always exits after the first match.

```yaml
- choose:
    - conditions:
        - condition: state
          entity_id: input_select.mode
          state: "away"
      sequence:
        - action: alarm_control_panel.arm_away
    - conditions:
        - condition: state
          entity_id: input_select.mode
          state: "home"
      sequence:
        - action: alarm_control_panel.disarm
  default:
    - action: notify.notify
      data:
        message: "Unknown mode"
```

**Gaps vs WebCoRE:**
- HA `choose` uses full conditions (not a simple equality match against an expression)
- No fall-through mode in HA
- No range matching in HA `choose` (requires template condition)
- WebCoRE's switch can subscribe to events on the switch expression; HA cannot

---

### 1.6 — `for` (For Loop)

**What WebCoRE does:**  
Repeats contained statements a preset number of times. Takes a start value, end value, and step. Counter variable (optional) tracks current iteration. System variable `$index` is also available. Supports break.

**What HA has:**  
`repeat: count:` — repeats a sequence a fixed number of times. Counter available as `repeat.index` (1-based). No start/end/step concept — only count. For variable step or non-1-start, use a `variables` action inside the loop.

```yaml
- repeat:
    count: 5
    sequence:
      - action: light.toggle
        target:
          entity_id: light.hall
      - delay:
          seconds: 1
```

**Gaps vs WebCoRE:**
- HA only supports counted repeat, not start/end/step
- `repeat.index` starts at 1 (not the start value)
- No equivalent of WebCoRE's counter variable auto-update at each step
- HA `repeat` supports `break` only via a `condition` action that stops the current iteration; there is no explicit `break` keyword

---

### 1.7 — `each` (For Each Loop)

**What WebCoRE does:**  
Iterates over a list of devices. Each iteration receives the current device as a variable (default: `$device`). Useful for applying the same action to each device in a dynamically-resolved list.

**What HA has:**  
`repeat: for_each:` — iterates over a list of items. Current item available as `repeat.item`. Can iterate over entity ID lists.

```yaml
- repeat:
    for_each:
      - light.kitchen
      - light.living_room
      - light.bedroom
    sequence:
      - action: light.turn_off
        target:
          entity_id: "{{ repeat.item }}"
```

**Gaps vs WebCoRE:**
- HA `for_each` iterates over a static or template-generated list, not a live device group
- No direct equivalent of WebCoRE's device-variable iteration where the variable holds device capability context
- HA `repeat.item` is a raw value; WebCoRE `$device` carries full device context (attributes, commands)

---

### 1.8 — `while` (While Loop)

**What WebCoRE does:**  
Checks conditions before each iteration. Executes contained statements as long as the conditions are true. Exits when conditions become false or `break` is encountered. Condition check happens at the top of each loop pass.

**What HA has:**  
`repeat: while:` — evaluates conditions before each iteration. Accepts HA condition list or shorthand template. Loop exits when conditions are false.

```yaml
- repeat:
    while:
      - condition: state
        entity_id: input_boolean.keep_running
        state: "on"
      - condition: template
        value_template: "{{ repeat.index <= 20 }}"
    sequence:
      - action: script.do_something
      - delay:
          seconds: 5
```

**Gaps vs WebCoRE:**
- HA while conditions are AND-combined; XOR has no native equivalent
- HA has no `break` keyword — must use a variable flag condition to exit early
- HA while loops can run forever if condition stays true; WebCoRE has the same behavior but the piston execution timeout is a backstop

---

### 1.9 — `repeat` (Repeat / Repeat Until)

**What WebCoRE does:**  
Executes contained statements first, then checks conditions. Repeats until conditions are true (do-while / repeat-until semantics). Always runs at least once. Exits when conditions become true or `break` is encountered.

**What HA has:**  
`repeat: until:` — runs sequence first, then checks conditions. Exits when conditions are true.

```yaml
- repeat:
    sequence:
      - action: shell_command.try_something
      - delay:
          milliseconds: 200
    until:
      - condition: state
        entity_id: binary_sensor.success
        state: "on"
```

**Gaps vs WebCoRE:**
- Same gaps as `while` — no native XOR, no explicit `break`, same timeout considerations

---

### 1.10 — `every` (Timer)

**What WebCoRE does:**  
Schedules repeated execution at a defined interval. Supports milliseconds, seconds, minutes, hours, days, weeks, monthly (specific day), and yearly (specific day of month). Supports "at this time" for sub-day precision (e.g., every day at 8:00am). Supports restriction filters: only during certain hours, days of week, days of month, weeks of month, months of year. Does NOT require an external trigger — the timer itself wakes the piston.

**What HA has:**  
Two trigger types cover the timer use cases:

**`time_pattern` trigger** — fires at regular intervals defined by hour/minute/second patterns (cron-like). Best for "every N minutes/hours."

```yaml
trigger:
  - trigger: time_pattern
    minutes: "/15"  # every 15 minutes
```

**`time` trigger** — fires once per day at a specific time. Best for "every day at X."

```yaml
trigger:
  - trigger: time
    at: "08:00:00"
```

**`sun` trigger** — fires at sunrise/sunset with optional offset.

```yaml
trigger:
  - trigger: sun
    event: sunset
    offset: "-00:30:00"
```

**Gaps vs WebCoRE:**
- HA has no single trigger that combines "every N days at time T" with day/week/month filters
- Monthly/yearly scheduling requires complex combinations or an `input_datetime` helper
- WebCoRE's sub-minute interval (every 5 seconds) maps to `time_pattern` with seconds, but HA docs note these are resource-intensive — same warning WebCoRE has
- `for` (duration persistence) survives config only until HA restart — WebCoRE timers survive restarts

---

### 1.11 — `break` (Break)

**What WebCoRE does:**  
Immediately exits the innermost enclosing loop (for, for each, while, repeat) or switch statement. Execution continues with the statement after the loop/switch.

**What HA has:**  
No explicit `break` action. To exit a loop early in HA:
- Inside `while`: use a condition that evaluates false
- Inside `until`: use a condition that evaluates true  
- Inside `repeat: count:`: use a template variable flag checked in a `while` condition
- Inside `choose`: not applicable (choose always exits after first match)

The practical workaround is a boolean variable flag set inside the loop and checked by the `while`/`until` condition.

**Gaps vs WebCoRE:**  
No direct equivalent — requires workaround pattern.

---

### 1.12 — `exit` (Exit)

**What WebCoRE does:**  
Immediately stops piston execution and sets the piston state to the provided value. No further statements run.

**What HA has:**  
`stop` action — stops a script sequence immediately.

```yaml
- alias: "Stop if paulus not home"
  stop: "Paulus is not home"
  enabled: true
```

Can also use `condition` action at the top level — if the condition fails, execution stops.

**Gaps vs WebCoRE:**
- HA `stop` does not set a piston state (no equivalent concept)
- HA `stop` in a nested context only stops the current sequence block, not the entire automation

---

## Section 2 — Comparison Operator Behavioral Pairing

WebCoRE's comparison operators come from `db.comparisons.conditions` and `db.comparisons.triggers` — served from backend. The behavioral categories are defined in the source. This section maps each category to HA equivalents.

### 2.1 — Condition Operators (evaluate current state)

These check what is true RIGHT NOW when the condition is evaluated. In HA these are `condition:` blocks.

| WebCoRE operator | What it does | HA equivalent |
|---|---|---|
| **is** / **is equal to** | Current value exactly equals the comparison value | `condition: state` with `state:` value, or `condition: numeric_state` with matching `above`/`below` bounds |
| **is not** / **is different than** | Current value does not equal the comparison value | `condition: state` with `state:` list (not the value), or template condition |
| **is less than** | Numeric value strictly below threshold | `condition: numeric_state` with `below:` |
| **is less than or equal to** | Numeric value at or below threshold | `condition: numeric_state` with `below:` set to value+1, or template |
| **is greater than** | Numeric value strictly above threshold | `condition: numeric_state` with `above:` |
| **is greater than or equal to** | Numeric value at or above threshold | `condition: numeric_state` with `above:` set to value-1, or template |
| **is between** | Numeric value within a range (exclusive) | `condition: numeric_state` with both `above:` and `below:` |
| **is not between** | Numeric value outside a range | Template condition |
| **is even** | Numeric value is divisible by 2 | Template: `{{ (value \| int) % 2 == 0 }}` |
| **is odd** | Numeric value not divisible by 2 | Template: `{{ (value \| int) % 2 != 0 }}` |
| **contains** | String value contains substring | Template: `{{ 'substring' in value }}` |
| **does not contain** | String value does not contain substring | Template: `{{ 'substring' not in value }}` |
| **starts with** | String begins with prefix | Template: `{{ value.startswith('prefix') }}` |
| **ends with** | String ends with suffix | Template: `{{ value.endswith('suffix') }}` |
| **matches** | String matches a regular expression | Template: `{{ value \| regex_match('pattern') }}` |
| **is any of** | Value is in a list of values | `condition: state` with a `state:` list |
| **is not any of** | Value is not in a list of values | Template or `not` condition wrapping state list |
| **was** / **was equal to** (timed) | Value equaled X during the past N duration | `condition: state` with `for:` parameter — checks current state has been X for at least that duration |
| **was not** (timed) | Value did not equal X during the past N duration | Template condition |
| **stayed** / **stayed equal to** | Value has been X for at least N duration without interruption | `condition: state` with `for:` |
| **stayed between** | Numeric value has been in range for at least N duration | `condition: numeric_state` with `for:` |

**Key behavioral note — `was` vs `stayed`:**  
In WebCoRE, `was equal to X for N` ("stayed") checks that the value has been continuously X for the specified period. `was equal to X in the last N` checks if the value was X at any point in the last N period. HA's `condition: state` with `for:` matches the "stayed" semantic — it only passes if the entity has been in that state continuously for the duration.

---

### 2.2 — Trigger Operators (detect state changes)

These fire when something CHANGES. In HA these become `trigger:` blocks in automations.

| WebCoRE operator | What it does | HA equivalent |
|---|---|---|
| **changes** | Value changes to anything different | `trigger: state` with no `from`/`to` (any change), but set `to: null` to avoid attribute-only changes |
| **changes to** | Value changes to a specific value | `trigger: state` with `to:` |
| **changes from** | Value changes away from a specific value | `trigger: state` with `from:` |
| **changes to between** | Numeric value crosses into a range | `trigger: numeric_state` with `above:` and `below:` |
| **changes from between** | Numeric value crosses out of a range | Not directly supported — requires two separate triggers with template filter |
| **changes to above** | Numeric value crosses upward past threshold | `trigger: numeric_state` with `above:` (fires on upward crossing only) |
| **changes to below** | Numeric value crosses downward past threshold | `trigger: numeric_state` with `below:` (fires on downward crossing only) |
| **stays equal to** (trigger) | Value changes to X and stays there for N duration | `trigger: state` with `to:` and `for:` |
| **stays not equal to** | Value changes away from X and stays away for N duration | `trigger: state` with `from:` and `for:` |
| **stays between** | Numeric value enters range and stays for N duration | `trigger: numeric_state` with `above:`, `below:`, and `for:` |
| **stays above** | Numeric crosses above threshold and stays there for N duration | `trigger: numeric_state` with `above:` and `for:` |
| **stays below** | Numeric crosses below threshold and stays there for N duration | `trigger: numeric_state` with `below:` and `for:` |

**Critical HA behavior note on `numeric_state` trigger:**  
HA fires `numeric_state` only when the value **crosses** the threshold — it must have been on the other side first. If the value is already above 30 and changes from 31 to 32, the trigger does NOT fire. WebCoRE's "changes to above" fires on any change that results in the value being above the threshold, regardless of prior state — this is a behavioral difference that must be handled with a `state` trigger + template filter if exact parity is needed.

**Critical HA behavior note on `for:` (duration):**  
HA's `for:` parameter on triggers does NOT survive a Home Assistant restart or automation reload. Any automation waiting for a duration fires when the timer is reset at restart. WebCoRE pistons also reset on restart, so this behavior is equivalent.

---

### 2.3 — Time / Virtual Device Comparisons

These compare against system-level virtual values — time, mode, etc.

| WebCoRE virtual operand | What it checks | HA equivalent |
|---|---|---|
| **time** is between X and Y | Current time is within a time window | `condition: time` with `after:` and `before:` |
| **time** is after X | Current time is past a specific time | `condition: time` with `after:` |
| **time** is before X | Current time is before a specific time | `condition: time` with `before:` |
| **time** + day/week filters | Time window with day-of-week restriction | `condition: time` with `after:`, `before:`, and `weekday:` |
| **date** comparisons | Current date matching criteria | `condition: template` using `now()` |
| **sunrise** / **sunset** preset | Compare against sun event times | `condition: sun` with `after:` / `before:` set to `sunrise`/`sunset`, with optional `offset` |
| **location mode** | Current HA area / zone state | `condition: state` on the mode entity (HA uses `zone.home`, presence trackers, etc.) |
| **every** + time-of-day | Execute at specific time each interval | `trigger: time` or `trigger: time_pattern` |

---

## Section 3 — Logical Operators Pairing

WebCoRE condition groups use AND / OR / XOR / "Followed by" as the group operator.

| WebCoRE operator | What it does | HA equivalent |
|---|---|---|
| **AND** | All conditions must be true | Default behavior — list conditions sequentially or use `condition: and` |
| **OR** | Any condition must be true | `condition: or` with nested conditions |
| **XOR** | Exactly one condition must be true | No native equivalent — template condition required: `{{ (cond1 \| int) + (cond2 \| int) == 1 }}` |
| **NOT** (negation) | Invert the result of the group | `condition: not` wrapping the group |
| **Followed by** | Conditions must occur in sequence within a time window | No native equivalent — requires `wait_for_trigger` chained steps with timeout tracking |

---

## Section 4 — Restrictions Behavioral Pairing

WebCoRE restrictions are conditions that gate execution but do NOT cause the piston to subscribe to events. They are re-evaluated on each piston run.

**HA equivalent:** A `condition:` action placed before the restricted statements in the sequence. Like restrictions, HA inline conditions don't subscribe to events — they only test state at evaluation time.

```yaml
# WebCoRE: "only when" restriction on a statement
# HA equivalent: inline condition action
- condition: state
  entity_id: input_boolean.enabled
  state: "on"
- action: light.turn_on   # only runs if condition passed
  target:
    entity_id: light.hall
```

**Gap:** WebCoRE restrictions can be placed at the piston level (global gate) or at the statement level. HA supports this same pattern — a condition at the top of the action sequence acts as a global gate; a condition mid-sequence acts as a local gate.

---

## Section 5 — Key Architectural Differences Summary

| Concept | WebCoRE | Home Assistant |
|---|---|---|
| Execution model | Piston runs on event, evaluates full script sequentially | Automation runs on trigger, evaluates conditions, runs actions |
| Nested triggers | Supported (`on` statement) | Not supported — triggers are automation-level only |
| Loop types | for, for each, while, repeat-until, explicit break | repeat: count, for_each, while, until — no explicit break |
| Event subscription granularity | Per-condition (individual conditions subscribe independently) | Per-automation (all triggers defined at the top) |
| Duration persistence across restart | Resets on restart (same as HA) | Resets on restart |
| State machine | Pistons have a piston state (true/false/custom) | No equivalent — automations are stateless |
| Parallelism | Async flag per statement | `parallel` action block |
| Variable scope | Local (piston-scoped) + global (instance-scoped) | Local (automation-run-scoped) + `input_*` helpers (persistent) |
| XOR logic | Native | Template only |
| Switch fall-through | Supported | Not supported (`choose` always exits after first match) |
| `for:` survival across restart | No (resets) | No (resets) — same behavior |

---

## Section 6 — Items That Cannot Be Mapped

These WebCoRE features have no HA equivalent and are confirmed cut per HA_LIMITATIONS.md:

| WebCoRE feature | Why it cannot map |
|---|---|
| **Followed by** condition group | HA has no sequential event chaining within a single automation run |
| **On event** nested trigger | HA triggers are automation-level — cannot nest inside action sequence |
| **Physical vs programmatic interaction** filter | HA has no reliable way to distinguish hardware button press from software state change for most devices |
| **XOR** logical operator | No native — template workaround only, not exposed in wizard |
| **Piston state** (exit with value) | No equivalent concept in HA automations |
| **Task Execution Policy** (execute only on condition state change) | No equivalent in HA script syntax |
| **Switch fall-through** | HA `choose` always exits after first match |
| **AskAlexa / EchoSistant** virtual devices | Platform-specific, deprecated |
| **IFTTT virtual device** | IFTTT integration exists in HA but works differently |
| **LIFX cloud** virtual device | HA LIFX integration uses local entity commands directly |
| **Contacts / SMS** | No equivalent in HA — use `notify` service |
| **Routines** (SmartThings-specific) | No equivalent — HA uses scripts/scenes |
