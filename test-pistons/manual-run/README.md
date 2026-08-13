# Manual-run pistons — NO TRIGGERS, started by hand

These 8 have **no triggers at all**. Jeremy runs them from webCoRE's **Test
button**; they are sound/light/notification benches, not automations.

They are separated so nobody has to work that out again. Reading `wakes = 0` on
one of these is CORRECT; reading it on anything in the parent folder means the
trigger was missed — and that ambiguity hid a real bug, where 5 genuinely
triggered pistons (including `29_Gas_Detector_2`) read as "nothing starts this"
and looked exactly like these.

They compile to HA **scripts**, which is what webCoRE's Test button targets.

Kept out of `test-pistons/*.json` deliberately: the snapshot harness globs that
folder, and a piston with no triggers exercises none of the trigger paths, so
it inflates the corpus count without testing anything triggered.
