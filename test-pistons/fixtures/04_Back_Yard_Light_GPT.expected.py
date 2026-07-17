# ═══════════════════════════════════════════════════════════════════════════
# GOLDEN FIXTURE — expected compiler output (hand-written 2026-07-15, NO compiler exists yet)
# Source piston: test-pistons/04_Back_Yard_Light_GPT.json  ("Back Yard Light GPT")
# Band: PyScript — routed by the `cancelTasks` task command (COMPILER_SPEC.md §3.2);
#   deploy path /config/pyscript/scripts/pistoncore/ per PYSCRIPT_COMPILER_RESEARCH §2.
# Exercises intent patterns (§3.0): #1 trigger-gated action, #2 compound-guard action,
#   #3 physical-vs-programmatic flag (DECIDED: replicate verbatim), #4 timed follow-up
#   with re-check, #5 explicit cancel-on-retrigger.
#
# BEHAVIORAL REVIEW: APPROVED (Jeremy, 2026-07-16 — "matches my intent"), including
#   both REVIEW POINTs below. This fixture is a binding acceptance target.
#   1. Lights turn off (any reason) -> reset both tracking flags.
#   2. Person seen on camera OR motion active, while dark (<100 lux) and lights off
#      -> lights on, mark "programatic" (the piston did it), clear manual override.
#   3. Lights turn on when the piston DIDN'T do it (programatic false)
#      -> mark manual override (a human did it; the piston keeps hands off).
#   4. Person leaves camera view OR motion stops, while piston owns the light
#      -> wait 10 minutes, re-check everything still quiet AND no manual override
#      -> lights off, release ownership. New person/motion during the wait cancels it.
#   5. Person/motion while a shutoff countdown is pending -> cancel the countdown.
#
# COMPILE DECISIONS EXERCISED (each needs Jeremy's behavioral blessing):
#   - LOCAL boolean variables are cross-run state -> persisted pyscript entities
#     (state.persist, PYSCRIPT_COMPILER_RESEARCH §7). On the YAML band these would be
#     input_boolean helpers (C-TYPES) — bands differ in storage, piston lives on one band.
#   - One function, all subscribed triggers as OR'd decorators, body re-evaluates all
#     statements top-to-bottom per wake (§2.5 point 1's one-pass model). Per-statement
#     trigger-conditions check "did MY event fire" via var_name/value/old_value kwargs.
#   - @task_unique = TCP approximation: ANY new subscribed event kills an in-flight run
#     (including the pending 10-min sleep). For THIS piston that matches webCoRE exactly,
#     because every subscribed event flips some guarding condition — but it is a known
#     over-approximation in general (§2.5 point 4 scoping caveat, mirrored from YAML band).
#   - `cancelTasks` ($19, $46): structurally satisfied by @task_unique restart semantics
#     (there is never a second pending task to cancel); emitted as breadcrumb only.
#     REVIEW POINT: confirm this reading, or require an explicit mechanism.
#   - changes_away_from -> `.old == X and now != X` (verbatim .old row, §3.3 table).
#   - Numeric compare via forgiving helper + None-check (locked §3.3 rule), fails closed.
#   - Placeholder entity_ids (resolution map decides real ones at compile time):
#       Device_Lights  :8a65e7ed...: -> light.back_yard_lights
#       Camera_Motion  :963f279b...: -> sensor.back_camera_smart_detect_type (Stage 3.2)
#       Motion_Sensor  :92eb7fd1...: -> binary_sensor.back_yard_motion
#       @Light_Sensor (global)       -> sensor.outdoor_illuminance
#   - <pid> placeholder = the piston's real hex id at compile time; "04backyard" here.
# ═══════════════════════════════════════════════════════════════════════════
# PistonCore compiled piston — Back Yard Light GPT (04backyard)
# Generated <timestamp> — template band pyscript/2.x — DO NOT EDIT

LIGHTS = "light.back_yard_lights"
DETECT = "sensor.back_camera_smart_detect_type"
MOTION = "binary_sensor.back_yard_motion"
LUX = "sensor.outdoor_illuminance"
PROG = "pyscript.pistoncore_04backyard_programatic"
OVERRIDE = "pyscript.pistoncore_04backyard_manualoveride"

task.unique("pistoncore_04backyard")           # kill in-flight old version on redeploy
state.persist(PROG, default_value="false")     # local var: programatic (boolean)
state.persist(OVERRIDE, default_value="false") # local var: manualOveride (boolean)


# Subscribed trigger set (every ct:"t"/s:true node): $2, $12, $13, $21, $27, $28
@state_trigger(f"{LIGHTS} == 'off'", state_hold_false=0)                        # $2
@state_trigger(f"{DETECT} == 'person'", state_hold_false=0)                     # $12/$43
@state_trigger(f"{MOTION} == 'on'", state_hold_false=0)                         # $13/$28-group
@state_trigger(f"{LIGHTS} == 'on'", state_hold_false=0)                         # $21
@state_trigger(f"{DETECT}.old == 'person' and {DETECT} != 'person'")            # $27 changes_away_from
@state_trigger(f"{MOTION} == 'off'", state_hold_false=0)                        # $28
@task_unique("pistoncore_04backyard")
def piston_04backyard(trigger_type=None, var_name=None, value=None,
                      old_value=None, **kwargs):
    log.info(f"[04backyard] wake: {var_name} {old_value}->{value}")

    # ── $1: if Device_Lights' switch changes to off ──────────────────────────
    if var_name == LIGHTS and value == "off":
        light.turn_off(entity_id=LIGHTS)            # $4 — faithful even if redundant
        state.set(PROG, "false")                    # $6
        state.set(OVERRIDE, "false")                # $7
        log.info("[04backyard] $1: lights off — flags reset")

    # ── $8: if lux < 100 AND lights off AND (person-trigger OR motion-trigger) ─
    person_fired = var_name == DETECT and value == "person"                     # $12
    motion_fired = var_name == MOTION and value == "on"                         # $13
    lux = state.get(LUX).as_float(default=None)     # forgiving helper, fails closed
    if (lux is not None and lux < 100                                           # $9
            and state.get(LIGHTS) == "off"                                      # $10
            and (person_fired or motion_fired)):                                # $11 group (or)
        light.turn_on(entity_id=LIGHTS)             # $15
        state.set(PROG, "true")                     # $17
        state.set(OVERRIDE, "false")                # $18
        # $19 cancelTasks: satisfied structurally — @task_unique already killed any
        # pending countdown when this event arrived. Breadcrumb only.
        log.info("[04backyard] $8: dark + presence — lights on (programatic)")

    # ── $20: if lights change to on AND programatic is false ────────────────
    # (the physical-vs-programmatic pattern, compiled VERBATIM per DECISION 2026-07-15)
    if (var_name == LIGHTS and value == "on"                                    # $21
            and state.get(PROG) == "false"):                                    # $22
        state.set(OVERRIDE, "true")                 # $24
        log.info("[04backyard] $20: manual light-on detected — override set")

    # ── $25: if (person left OR motion stopped) AND programatic true ────────
    person_left = var_name == DETECT and old_value == "person" and value != "person"  # $27
    motion_stopped = var_name == MOTION and value == "off"                            # $28
    if (person_left or motion_stopped) and state.get(PROG) == "true":           # $26/$29
        log.info("[04backyard] $25: area quiet — 10 min shutoff countdown")
        task.sleep(600)                             # $31 wait 10 min ($30)
        # ── $32: post-wait re-check (all current-state conditions) ──────────
        if (state.get(MOTION) == "off"                                          # $33
                and state.get(DETECT) != "person"                               # $34
                and state.get(PROG) == "true"                                   # $35
                and state.get(OVERRIDE) == "false"                              # $36
                and state.get(LIGHTS) == "on"):                                 # $37
            light.turn_off(entity_id=LIGHTS)        # $39
            state.set(PROG, "false")                # $41
            log.info("[04backyard] $32: still quiet — lights off, released")

    # ── $42: if person detected OR motion active -> cancel pending shutoff ──
    person_now = var_name == DETECT and value == "person"                       # $43
    if person_now or state.get(MOTION) == "on":                                 # $44 (is-condition)
        # $46 cancelTasks: same structural satisfaction as $19 — the wake that got
        # here already killed any in-flight countdown via @task_unique. Breadcrumb only.
        log.info("[04backyard] $42: presence — any pending shutoff is cancelled")


@service("pyscript.pistoncore_04backyard_execute")
def piston_04backyard_execute(**kwargs):
    """PistonCore: execute piston 'Back Yard Light GPT'."""
    piston_04backyard(trigger_type="service", **kwargs)
