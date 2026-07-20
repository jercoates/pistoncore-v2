// First-run wizard (SESSION_BRIEF_FIRST_RUN.md). Guided path over the SAME
// settings the Settings page owns — this file never invents a store, it POSTs
// to /api/settings like Settings does. Every step is skippable; the write
// probe (step 2) is the only real gate, because step 3 writes THROUGH it.

const el = (id) => document.getElementById(id);
const steps = document.querySelectorAll(".setup-step");

const state = { connected: false, probeOk: false, addon: false };

function setStepState(n, kind, text) {
  const step = document.querySelector('.setup-step[data-step="' + n + '"]');
  if (!step) return;
  step.classList.remove("done", "skipped", "blocked");
  if (kind) step.classList.add(kind);
  const badge = step.querySelector("[data-state]");
  badge.textContent = text || "";
  badge.className = "setup-state " + (kind || "");
}

function open(n) {
  steps.forEach((s) => s.classList.toggle("open", Number(s.dataset.step) === n));
}

function banner(node, kind, msg) {
  node.innerHTML = "";
  const d = document.createElement("div");
  d.className = "banner banner-" + kind;
  d.textContent = msg;
  node.appendChild(d);
}

function settingsParams() {
  return new URLSearchParams({
    ha_url: el("ha_url").value,
    ha_token: el("ha_token").value,
    write_mode: el("write_mode").value,
    ha_config_path: el("ha_config_path").value,
    smb_host: el("smb_host").value,
    smb_share: el("smb_share").value,
    smb_username: el("smb_username").value,
    smb_password: el("smb_password").value,
    tts_engine: el("tts_engine").value,
  });
}

const saveSettings = () =>
  fetch("/api/settings?" + settingsParams().toString(), { method: "POST" });

// Any step can be re-opened by clicking its header — skipping or finishing a
// step must never trap the user (they may want to come back before leaving).
steps.forEach((s) => {
  s.querySelector(".setup-step-head").addEventListener("click", () => {
    open(Number(s.dataset.step));
  });
});

// ── step 0: deployment detection (defaults only) ──────────────────────────
async function detect() {
  const resp = await fetch("/api/setup/detect");
  if (!resp.ok) return;
  const d = await resp.json();
  if (d.note) {
    el("detect-note").style.display = "";
    el("detect-note").textContent = d.note;
  }
  if (d.write_mode) el("write_mode").value = d.write_mode;
  if (d.ha_config_path) el("ha_config_path").value = d.ha_config_path;
  if (d.smb_host && !el("smb_host").value) el("smb_host").value = d.smb_host;
  syncMode();
  if (d.deployment === "addon") {
    state.addon = true;
    state.connected = true;
    el("conn-fields").style.display = "none";
    el("conn-save").style.display = "none";
    setStepState(1, "done", "Add-on — connected automatically");
    open(2);
    loadExtras();
  }
}

// ── step 1: connection ────────────────────────────────────────────────────
el("conn-save").addEventListener("click", async () => {
  banner(el("conn-banner"), "info", "Connecting…");
  await saveSettings();
  const resp = await fetch("/api/setup/pyscript-check"); // cheapest real round trip
  const data = await resp.json();
  if (data.status === "unknown") {
    banner(el("conn-banner"), "info", data.message || "Could not reach Home Assistant.");
    setStepState(1, "blocked", "not connected");
    return;
  }
  state.connected = true;
  banner(el("conn-banner"), "success", "Connected to Home Assistant.");
  setStepState(1, "done", "connected");
  open(2);
  loadExtras();
});

// ── step 2: write target (the gate) + runtime extras ──────────────────────
function syncMode() {
  const smb = el("write_mode").value === "smb";
  el("local-fields").style.display = smb ? "none" : "";
  el("smb-fields").style.display = smb ? "" : "none";
}
el("write_mode").addEventListener("change", syncMode);

el("probe-run").addEventListener("click", async () => {
  banner(el("probe-banner"), "info", "Testing…");
  await saveSettings();
  const resp = await fetch("/api/settings/test-write", { method: "POST" });
  const data = await resp.json();
  if (!resp.ok) {
    state.probeOk = false;
    banner(el("probe-banner"), "error", data.error || "Could not write. Fix the settings above and test again.");
    setStepState(2, "blocked", "no write access");
    setStepState(3, "blocked", "needs step 2");
    return;
  }
  state.probeOk = true;
  banner(el("probe-banner"), "success", "Write access confirmed — " + data.target);
  setStepState(2, "done", "can write");
  setStepState(3, null, "");
  open(3);
});

async function loadExtras() {
  // PyScript presence — informational, never a blocker
  try {
    const r = await fetch("/api/setup/pyscript-check");
    const d = await r.json();
    if (d.status === "missing") {
      banner(el("pyscript-banner"), "info",
        "PyScript is not installed in Home Assistant. Simple pistons still compile " +
        "and run as normal HA automations, but pistons that use formulas, loops, " +
        "switches, variables, event blocks, or computed messages need it. Install " +
        "it from HACS (search “pyscript”) any time — nothing here breaks without it.");
    } else if (d.status === "installed") {
      banner(el("pyscript-banner"), "success", "PyScript is installed — every kind of piston can run.");
    }
  } catch (e) { /* informational only */ }

  // TTS engines come from the settings page's own source of truth
  try {
    const r = await fetch("/settings");
    const html = await r.text();
    const doc = new DOMParser().parseFromString(html, "text/html");
    const src = doc.getElementById("tts_engine");
    if (src) el("tts_engine").innerHTML = src.innerHTML;
  } catch (e) { /* optional */ }
}

// ── step 3: configuration.yaml (locked behind the probe) ──────────────────
el("cy-check").addEventListener("click", async () => {
  if (!state.probeOk) {
    banner(el("cy-banner"), "info",
      "Finish step 2 first — PistonCore edits configuration.yaml through the " +
      "write target, so it has to work before this can run.");
    return;
  }
  el("cy-changes").style.display = "none";
  banner(el("cy-banner"), "info", "Checking…");
  const resp = await fetch("/api/config-yaml");
  const data = await resp.json();
  if (!resp.ok) { banner(el("cy-banner"), "error", data.error || "Check failed."); return; }
  if (data.status === "ok") {
    banner(el("cy-banner"), "success", data.message);
    setStepState(3, "done", "already set up");
    open(4);
    return;
  }
  el("cy-list").innerHTML = "";
  (data.changes || []).forEach((c) => {
    const li = document.createElement("li"); li.textContent = c; el("cy-list").appendChild(li);
  });
  (data.refusals || []).forEach((r) => {
    const li = document.createElement("li"); li.textContent = "⚠ " + r; el("cy-list").appendChild(li);
  });
  if ((data.changes || []).length) {
    banner(el("cy-banner"), "info", "These exact lines will be added (a timestamped backup is written first):");
    el("cy-changes").style.display = "";
  } else {
    banner(el("cy-banner"), "info", "PistonCore can't edit this file automatically:");
    el("cy-changes").style.display = "";
    el("cy-apply").style.display = "none";
  }
});

el("cy-apply").addEventListener("click", async () => {
  banner(el("cy-banner"), "info", "Applying…");
  const resp = await fetch("/api/config-yaml/apply", { method: "POST" });
  const data = await resp.json();
  if (!resp.ok) { banner(el("cy-banner"), "error", data.error || "Apply failed."); return; }
  el("cy-changes").style.display = "none";
  banner(el("cy-banner"), "success",
    (data.applied || []).join("; ") + ". Backup: " + (data.backup || "n/a") +
    " — now reloading Home Assistant's YAML…");
  setStepState(3, "done", "configured");
  const r = await fetch("/api/ha/reload-yaml", { method: "POST" });
  const d = await r.json();
  banner(el("cy-banner"), r.ok ? "success" : "info", r.ok
    ? "Done — Home Assistant reloaded its configuration and can now see PistonCore's folders."
    : (d.error || "Applied, but the reload failed — restart HA (Settings → System → Restart)."));
  open(4);
  summarize();
});

// ── skips ─────────────────────────────────────────────────────────────────
document.querySelectorAll(".setup-skip").forEach((btn) => {
  btn.addEventListener("click", () => {
    const n = Number(btn.dataset.skip);
    setStepState(n, "skipped", "skipped — do it later in Settings");
    open(n + 1);
    if (n === 2) loadExtras();
    summarize();
  });
});

function summarize() {
  const pending = [];
  if (!state.connected) pending.push("connect to Home Assistant");
  if (!state.probeOk) pending.push("give PistonCore write access");
  el("finish-summary").textContent = pending.length
    ? "You can start now — but until you " + pending.join(" and ") +
      " in Settings, pistons won't reach Home Assistant."
    : "Everything's connected. Import or write a piston and it will compile straight into Home Assistant.";
}

// boot
detect();
open(1);
summarize();
