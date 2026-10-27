# SESSION BRIEF — How Claude drives the webCoRE editor

**DRAFT for Jeremy's review.** Hand this to a fresh Claude Code session on the dev
bench.

**No machine addresses, tokens or keys belong in this file** — the repo is public.
They live in `DEV_BENCH.local.md` (gitignored). Point at it; never copy from it.

---

## WHY THIS SESSION EXISTS

Sessions keep failing to operate the vendored editor — the old Angular webCoRE
dashboard. Jeremy drives it by eye and by hand, and that is not how a session can
drive it, so he cannot write these instructions himself. They have to come from a
session that has actually done every step on the bench.

**The editor is not just a way of typing values in.** When a device is rebound,
the editor re-derives everything that depends on it: which attributes are offered,
which commands, which operators, what each parameter expects. That is how a piston
written for one device adapts to another, and it is why testing has to go through
the editor — a piston changed any other way keeps selections made for the old
device.

**The deliverable is one section of text:** the steps for "Driving the editor",
to replace the `[JEREMY TO FILL …]` placeholder under PART 1 → *Driving the
editor* in `new docs/01_USING_PISTONCORE_DRAFT.md`. Every step must have been done
for real in this session and tagged `VERIFIED — <date>`. Anything you could not do
is written up as a failed step, never guessed at.

## READ FIRST, IN THIS ORDER

1. `CLAUDE.md`
2. `HARD_RULES.md`
3. `DEV_BENCH.local.md` — **all of it, not grepped.** Start with "RUNBOOK — BRING
   THE BENCH UP FROM COLD": it covers starting the bench, upgrading Home Assistant,
   the Hubitat link, starting PistonCore against it, and the pre-flight checks.
   Gitignored; if it is missing, ask Jeremy.
4. `new docs/01_USING_PISTONCORE_DRAFT.md` — Parts 0, 0.5, 1 and 3. Part 0 is the
   only allowed test path. Part 3 is the source of truth for variable types and
   encodings (task 4).

**The bench must be up and passed its pre-flight before you start.** If the runbook
does not get it there, stop and report where it failed — do not work around it.

## PRE-FLIGHT — before any Save that deploys

The runbook has the detail. Each of these has cost a whole session before.

1. **Every entity in the compiled output is `platform=virtual`.** Not just the ones
   you mean to drive. Any other platform is a real device in Jeremy's house.
2. **The bench's `configuration.yaml` includes PistonCore's automations folder.**
   If not, every "deployed" piston writes a file Home Assistant never reads.
3. **PistonCore Settings have an alarm panel and a TTS engine picked** — the alarm
   panel being the **virtual** bench panel, never his real keypad.
4. **Known shim bug:** a Settings save that omits any of alarm panel, TTS engine or
   email entity **blanks it**. Set them in one save and read them back. A setting
   that "won't stick" is this, not the editor.

## CHOOSING TEST DEVICES — this decides whether a test means anything

- **Clone the actual device the piston was written for** (`/test-devices`). A clone
  comes from the same driver, so it carries the same capability names and the
  piston's statements keep working. Use factory types (`/test-devices/debug`) only
  for kinds Jeremy does not own.
- **Do not pick a device by "best attribute match".** That puts a dimmer piston on
  a plain switch, and the statements then fail in ways that look like compiler
  bugs.
- **When a capability name still does not carry across** — a different driver for
  the same kind of device — open that statement in the editor and reselect through
  it. That re-derives the one selection. Record each time you had to.
- **Groups have the same quirk:** the right selection can drop out when the devices
  are held in a variable, and is fixed by reselecting in the statement.
- Anything grouped (any / all / each) gets 2–3 devices, with the one that trips
  NOT first.

## KNOWN TRAPS — found 2026-09 and 2026-10. RE-VERIFY, don't trust.

Start from these so you do not spend hours rediscovering them. Each still has to be
confirmed in this session before it goes into the deliverable. Several only exist
because a session is scripting the editor rather than clicking it.

- **Go to `/connect` first.** Without it Angular never boots: the page has no
  `ng-click` elements at all and looks like it is still loading.
- Piston rows on the front door are `[data-piston-id]` elements, not links.
- The piston body renders about 9 seconds after the page loads. Poll for real
  content; `wait_for_selector` races it.
- **The editor opens in view mode.** `editVariable()` does nothing until `edit()`
  has been called. `edit()` is reachable from any define row's Angular scope.
- Define rows are `[ng-click='editVariable(variable);']`, and each row's scope has
  `.variable.n`, the variable's name.
- Mouse clicks on a define row's blank space are swallowed (`dnd-nodrag`). Clicking the
  variable's chip text itself (the hash or device name) DID open the dialog in edit mode
  (VERIFIED — 2026-10-26).
- The device picker is `select[ng-model="operand.data.d"]`. `updateVariable()` and
  the piston's `save()` live on **ancestor** scopes.
- The variable dialog sometimes does not open on the first attempt. Settle and
  retry before calling it a failure.
- **Large pistons are saved in chunks** (`set.start` / `set.chunk` / `set.end`). The
  editor does this itself. A single-request save of a ~90 KB piston gets a bare
  `400 Invalid HTTP request`, which reads like the piston was refused. It wasn't.
- A failed save can leave an **empty named shell** in the piston list. Two of the
  same name usually means that, not a duplicate import.
- `document.body.innerText` on the piston's view screen gives webCoRE's own
  rendered script — the outside view for reading a piston's intent.
- Read a piston back with `GET /intf/dashboard/piston/get?id=<pid>` (JSONP — strip
  the `callback(…)` wrapper).

**Settled 2026-10-26:** the real picker is driven through the UI (open the
bootstrap-select button, type in its search box, click the option, close the picker by
clicking the dialog heading, then Save). Do not set the value on the scope. Whether a
scope-set fires the same change handling was not tested and does not need to be.

## TASKS, IN THIS ORDER

For each one, record how you operated it, what you tried that did not work and why,
and how you confirmed it took effect — always by reading the stored piston back
after the editor's own Save, never by trusting the screen.

1. **Open** the front door, open an existing piston in the editor, and open its
   view/status screen.
2. **Import a corpus piston through `/backup`** (paste, Import, Restore) and get its
   devices onto `Test — …` devices. **This is the one that matters most.** CORRECTED
   2026-10-26: there is NO "Rebuild piston items" remap for corpus files (webCoRE only
   shows it when a piston carries a legend, and none of the 154 does; a piston restored
   from a valid active backup code from the official online webCoRE does carry one and
   does bring up the screen, per Jeremy, not tried). The way to bind
   devices is to edit the VARIABLES in the define block at the top; do not bind inside
   statements when a variable holds the device. Some corpus pistons name a device
   *inline in a statement* with no variable (28 of 154); for those, binding in the
   statement is the only route. Say which you did.
3. Edit a **device variable** in the define block to hold 2–3 test devices of the
   right type (this is the normal way to bind, task 2). A device variable can also be
   filled with one controlled device plus read-only filler (draft Part 2.5).
4. Edit a **non-device local** — integer, boolean, string and time. Confirm each
   reads back with the type and encoding in Part 3 of the draft (for example, time
   as minutes since midnight).
5. Create and edit a **global** in the global-variables screen: one device global
   and one string global. Record the recompile prompt a device-global change
   raises.
6. Add or change **one condition and one action task** through the wizard dialogs,
   including **reselecting through a statement** whose capability name did not
   carry across from the original device.
7. **Save,** and confirm compile-on-save ran: the front-door status, and the
   status-screen banner if it failed. Then confirm Home Assistant actually has the
   automation and that it is on — "deployed" alone is not enough.
8. ~~Run a manual-run piston with the Test button.~~ REMOVED 2026-10-26: the Test
   button is not wired in PistonCore and is far down the list (Jeremy). Do not use it
   and do not report it as a fault. Test a piston by driving a virtual device so its
   trigger fires. How to start a no-trigger (manual-run) piston is undecided; do not
   invent a way, and keep manual-run pistons out of trigger testing.

## HARD LIMITS

- **Never edit anything under `dashboard/`.** It is sealed.
- **Never substitute a shortcut for an editor step** — no JSON edit, no direct
  `piston/set` call, no setting a picker's value straight onto its scope where a
  selection should happen, no hand-built piston, no hand-built device. The editor's
  own path is the thing being documented.
- **Session tooling already exists** in the bench folder (see the runbook). It
  imports through `piston/set` — exactly the shortcut this brief bans. Read it to
  compare notes; **it is not the deliverable** and must not be used to do any task.
- **If a step can't be done, STOP and record exactly where it failed.** That is a
  finding, not a reason to go around it.
- When the editor misbehaves, **suspect the shim first**, not the dashboard.
- Jeremy's test HA and his house are off limits. Anything that writes to his
  Hubitat hub needs his permission, every time.
- Plan first and wait for Jeremy's go. No new files without approval: the output
  is text for him to review. The one exception is keeping `DEV_BENCH.local.md`
  correct as you learn.

## OUTPUT FORMAT

A section Jeremy can paste into the draft, one block per task:

```
### <task>
VERIFIED — <date>
Steps:   numbered, exact
Traps:   what failed and why
Confirm: how the stored JSON proved it worked
```

Then, separately, a short list of anything that looked like a **shim bug**, each
with its evidence. Report them; don't fix them in this session.
