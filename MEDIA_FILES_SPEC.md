# PistonCore v2 — Media and File Handling Specification

> ## ⚠ READ BEFORE CHANGING ANYTHING
> **This spec may be out of date, and may be MISSING decisions that were made
> but never written down.** A spec can tell you what to **build**. It NEVER, on
> its own, authorises **undoing** something that already works.
>
> If the code does something this document doesn't mention, that is most likely
> a real decision — check `git log -S "<the thing>"` first, then **ASK JEREMY**.
> **Never delete working behaviour without his explicit go-ahead.** (Removing
> genuinely dead code is fine.)
>
> Standing decisions that outrank this document: **[HARD_RULES.md](HARD_RULES.md)**

**Scope:** how webCoRE image capture, image storage, audio playback, and speech
compile to Home Assistant. Covers where files are written, how they are named,
and what happens to them afterward.

**Status:** PARTIAL — storage location, filename scheme, and cleanup DECIDED.
Notification attachment and webCoRE-side image internals BLOCKED pending
`webcore-piston.groovy`.

**Relationship to other specs.** This document is the sole authority on media and
file handling. `VARIABLES_SPEC.md` covers variable storage and typing generally
and defers here for anything involving image or audio content. Device variables
are specified in `COMPILER_SPEC.md` and are out of scope for both.

## Sources

| Source | Version | Role |
|---|---|---|
| `webcore.groovy` (parent app) | v0.3.114.20220203 | Capability/attribute table |
| `piston.module.html` (dashboard) | v0.3.114.20220203 | `dialog-captured-image` template |
| User pistons (dashboard screenshots) | 2026-08-03 | Observed real-world usage |
| HA action docs (`camera.snapshot`, `image.snapshot`) | read 2026-08-03 | Write paths and permissions |
| HA core `components/image/` | read 2026-08-03 | Proxy URL and token rotation |
| `webcore-piston.groovy` | — | **NOT YET SUPPLIED** — image store internals |

Every claim is marked `Verified — <source, date>`, `Assumed — needs test`,
`Decision — PistonCore choice`, or `Open — decision needed` / `Open — needs
source`.

---

## 1. Core principle: media is referenced, never carried

**Verified — HA developer docs, image entity, read 2026-08-03.** An HA image
entity's state is driven by `image_last_updated`. The image bytes are fetched
separately and are never present in the entity state.

**Verified — HA `media_source` docs, read 2026-08-03.**
`media_player.play_media` takes a `media_content_id` — a `media-source://` URI,
a `/local/` path, or an https URL — plus a `media_content_type`.

**Decision — PistonCore choice.** No image or audio bytes ever enter an entity
state, a helper, or a variable. Media is always referenced by path or URI. This
is also forced by the platform: entity state is capped at 255 characters
(`VARIABLES_SPEC.md` §7.2), which makes by-value media impossible regardless.

**Verified — user piston "doorbell pushed albert", 2026-08-03.** webCoRE already
does the same. A captured image is held as a filename in a plain `string`
variable:

```
string DoorBell_Camera_Image = 'Doorbell_Pro_-motion_...-motion.jpg';
```

The representations therefore match, and a filename fits the state cap
comfortably.

---

## 2. Image capture

### 2.1 Never store a proxy URL

**Verified — HA core `components/image/__init__.py`, read 2026-08-03.**
`ENTITY_IMAGE_URL = "/api/image_proxy/{0}?token={1}"`, with
`TOKEN_CHANGE_INTERVAL = timedelta(minutes=5)`.

**Decision — PistonCore choice.** PistonCore must **never** store an
`/api/image_proxy/` or `/api/camera_proxy/` URL in a variable. This is a
prohibition, not a preference.

The token rotates every five minutes. A stored URL silently dies: a piston that
captures an image and notifies later sends a dead link, with no error raised
anywhere. It works every time it is tested by hand and fails whenever the
notification lags.

### 2.2 Where snapshots are written

**Verified — HA `camera.snapshot` and `image.snapshot` action docs, read
2026-08-03.** HA does not choose a location. The action takes a full path, and
that path must sit inside a directory HA is permitted to write to. **Two are
permitted by default with no configuration change:** the `www` folder inside the
configuration directory, and each configured media directory. Any other location
requires an `allowlist_external_dirs` entry under `homeassistant:` in
`configuration.yaml`.

**Decision — PistonCore choice.** Snapshots are written to
`/media/pistoncore/<camera>/`. **Not** `/config/www/`.

Rationale: `/config/www` is served publicly at `/local/` **with no
authentication**. Any file placed there is fetchable by anyone who knows or
guesses the URL. Camera captures of a residence must not sit behind a guessable
unauthenticated URL, particularly on an instance exposed through a reverse
proxy. Media directories are permitted by default, are not web-served, and are
reached through `media-source://` URIs that respect authentication.

**Both options are zero-config. Only one is safe.** Nothing fails and nothing
warns if the wrong one is chosen.

**Consequence for INSTALL.md.** No `allowlist_external_dirs` entry is required.
State this explicitly, and state *why* `/config/www` is not used — otherwise the
obvious-looking choice, widely recommended in community posts, gets reproduced
by anyone adapting the setup.

### 2.3 Filename scheme — static, overwritten

**Decision — PistonCore choice.** Snapshot filenames are **fixed per camera**.
Each capture overwrites the previous one. Path form:
`/media/pistoncore/<camera>/<camera>.jpg`.

What this buys, beyond bounded disk usage:

- **`clearImages()` becomes a no-op** with nothing left to specify (§2.4).
- **No reaper job, no cleanup service, no scheduled task.**
- **The image path is a compile-time constant.** It is known when the automation
  is emitted, so it is a literal string — none of the dynamic-value machinery in
  `VARIABLES_SPEC.md` applies to it.

**Divergence from webCoRE, accepted.** webCoRE retains images until
`clearImages()` is called. Under this scheme only the most recent capture per
camera exists. The observed usage pattern — capture, then immediately notify —
never reads an older image.

**Per-camera paths are required, not optional.** A single shared snapshot path
would let two cameras overwrite each other. Per-camera paths contain the failure
to one camera firing twice.

**Open — decision needed.** The narrow race this scheme has: if a camera fires
twice within a second or two, the second capture can land while the first
notification is still assembling its attachment, and the notification goes out
carrying the newer image. Timestamped filenames avoid it at the cost of
unbounded growth with no reaper. Whether this is worth solving is a judgment
call — two doorbell presses two seconds apart both showing the second visitor is
arguably correct behavior.

**Open — decision needed.** Whether to offer timestamped filenames as an opt-in
for pistons that genuinely need capture history. HA's documentation recommends
timestamping when separate files are wanted. If added, `clearImages()` must gain
a real implementation (§2.4).

### 2.4 `clearImages()`

**Verified — user piston "doorbell pushed albert", 2026-08-03.** The piston calls
`Take a picture;` and later `clearImages();` on the same camera device. webCoRE
owns an image store with an explicit lifecycle command to empty it.

**HA has no equivalent.** The snapshot action writes files; nothing reclaims
them.

**Decision — PistonCore choice.** Under the fixed-filename scheme (§2.3),
`clearImages()` compiles to a **no-op** — there is nothing to clear, because only
one file per camera ever exists and it is overwritten in place.

**Conditional obligation.** If timestamped filenames are ever added, this
decision expires and `clearImages()` requires a real implementation. Record the
dependency; do not let the no-op survive a naming-scheme change silently.

### 2.5 Attachment to notifications

**Verified — user piston "doorbell pushed albert", 2026-08-03.** An email
notification embeds the image filename via a `File:` parameter alongside the
message text.

**Open — needs source.** How webCoRE's `File:` parameter resolves a filename to
image data, and whether HA notify platforms accept an equivalent path. Resolved
by **MEDIA-V-01**.

**Assumed — needs test.** Whether an HA notify platform can attach a file from a
media directory, or whether attachment paths are subject to different
restrictions than snapshot write paths. If media directories turn out not to
work for attachment, §2.2's location decision must be revisited — this is the
single finding most likely to overturn it.

---

## 3. Audio and speech

**Decision — PistonCore choice.** webCoRE speech commands (`playText`, `speak`,
and variants) compile to `tts.speak`. The message is a plain string and needs no
special handling.

**Decision — PistonCore choice.** webCoRE `playTrack` compiles to
`media_player.play_media`.

**The gap:** `media_content_type` is **required by HA** and has **no webCoRE
equivalent** — webCoRE's track parameter is a bare URI.

**Decision — PistonCore choice.** The compiler infers `media_content_type` from
the file extension using a data-driven extension→type table, and fails loudly
when the extension is absent or unrecognized. The table is data, never inline in
the compiler or a template.

### 3.1 Device-specific numeric media

**Verified — user piston "doorbell pushed albert", 2026-08-03.**
`Play Sound 12;` on a chime device — a numeric sound index interpreted by device
firmware.

**Decision — PistonCore choice.** HA has no "sound N" concept; the meaning
depends entirely on the device integration. This is an **escape-hatch case**
under the hybrid vocabulary approach — raw HA terms supplied through webCoRE's
existing custom-text mechanism — not a translatable command.

---

## 4. Verification tasks (for Claude Code)

Run **one task per session.**

### Standing rules for every task

1. **Read the full file before drawing any conclusion.** Grep to locate; read to
   understand.
2. **webCoRE source is the highest authority.** Where source and this spec
   disagree, the source wins and this spec is wrong.
3. **Make no edits.** Report only.
4. **Cite file and line for every claim.** A claim without a citation is not an
   answer.
5. **Report unknowns as unknown.** Do not infer or fill gaps from general
   knowledge.
6. **Report in this format**, one block per finding:

   ```
   MEDIA-V-<task>-<n>
   CLAIM:    <what this spec says, or "no current claim">
   FINDING:  <what the source actually says>
   CITATION: <file> line <NNN>
   VERDICT:  CONFIRMS | CONTRADICTS | INCOMPLETE | NOT-FOUND
   ```

---

### MEDIA-V-01 — webCoRE image store and attachment

**Files:** `webcore-piston.groovy`, `webcore.groovy`

Report:

- Where captured images are physically stored, and the filename scheme —
  specifically whether names are unique per capture or reused.
- What `clearImages()` deletes: all images for a device, all for a piston, or all
  globally.
- Whether images expire, or are capped by count or total size.
- How the `File:` notification parameter resolves a filename to image data, and
  what the receiving notification handler is given — path, bytes, or URL.
- Whether the image filename variable is written automatically by the engine on
  `take`, or must be assigned by the piston.

The `dialog-captured-image` template in `piston.module.html` binds an `<img src>`
to a `capturedImage` value — determine what form that value takes (data URI,
URL, or path).

---

### MEDIA-V-02 — HA notify attachment paths

**Files:** Home Assistant core, `components/notify/` and the SMTP notify platform

**Spec claim under test (§2.5):** an HA notify platform can attach a file located
in a media directory.

Report:

- Which notify platforms support file attachment, and the parameter name used.
- Whether attachment paths are validated against `allowlist_external_dirs`, or
  against a different rule than snapshot write paths.
- Whether a media directory path is accepted for attachment without additional
  configuration.
- What happens when the referenced file does not exist — error, or silent send
  without attachment.

**This task can overturn §2.2.** If media directories are not usable for
attachment, the snapshot location decision must be revisited, and the alternative
must still avoid `/config/www` being publicly served.

---

### MEDIA-V-03 — Image and audio attribute types

**Files:** `webcore-piston.groovy`, `webcore.groovy`

**Context.** The capability/attribute table in `webcore.groovy` (lines ~2470–2560)
declares an `image` attribute type. The variable dialog offers no matching
variable type.

Report:

- What the engine does when an `image`-typed attribute is assigned to a variable:
  coerce to string, error, or store an object reference.
- The full set of media-related capabilities and their commands —
  `imageCapture`, chime/tone capabilities, speech and audio capabilities — with
  exact command names and parameter types.
- For chime-style capabilities, how the numeric sound index is passed and whether
  any metadata describes the available sounds.

---

## 5. Still unresolved

- Notification attachment path rules (MEDIA-V-01, MEDIA-V-02).
- webCoRE image store internals and `clearImages()` real scope (MEDIA-V-01).
- Whether the fixed-filename race (§2.3) warrants a mitigation.
- `media_content_type` extension→type table contents — needs building.
