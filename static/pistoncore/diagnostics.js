// Diagnostics — the compiler help/debug screen as a TOOL. Live system checks,
// real per-piston errors, the generated code in the browser (no file-share
// digging), and one-click evidence bundles.

const checksEl = document.getElementById("diag-checks");
const pistonsEl = document.getElementById("diag-pistons");

const LABEL = { deployed: "deployed", error: "compile error",
                pyscript: "needs PyScript", paused: "paused",
                pending: "not compiled" };

function checkRow(c) {
  const row = document.createElement("div");
  row.className = "diag-check " + (c.ok === true ? "ok" : c.ok === false ? "bad" : "unknown");
  const mark = document.createElement("span");
  mark.className = "diag-mark";
  mark.textContent = c.ok === true ? "✓" : c.ok === false ? "✕" : "?";
  const body = document.createElement("div");
  const name = document.createElement("div");
  name.className = "diag-name";
  name.textContent = c.name;
  const detail = document.createElement("div");
  detail.className = "field-hint";
  detail.textContent = c.detail || "";
  body.appendChild(name);
  body.appendChild(detail);
  if (c.fix) {
    const fix = document.createElement("div");
    fix.className = "diag-fix";
    fix.textContent = "Fix: " + c.fix;
    body.appendChild(fix);
  }
  row.appendChild(mark);
  row.appendChild(body);
  return row;
}

function pistonRow(p) {
  const wrap = document.createElement("div");
  wrap.className = "diag-piston";

  const head = document.createElement("div");
  head.className = "diag-piston-head";
  const name = document.createElement("span");
  name.className = "piston-name";
  name.textContent = p.name;
  const pill = document.createElement("span");
  pill.className = "compile-pill compile-" + p.status;
  pill.textContent = LABEL[p.status] || p.status;
  head.appendChild(name);
  head.appendChild(pill);
  wrap.appendChild(head);

  const body = document.createElement("div");
  body.className = "diag-piston-body";

  const msg = document.createElement("p");
  msg.className = p.status === "error" ? "diag-error-msg" : "field-hint";
  msg.textContent = p.message || "";
  body.appendChild(msg);

  const meta = [];
  if (p.file) meta.push("Deployed file: " + p.file);
  if (p.band) meta.push("Compiled as: " + (p.band === "pyscript" ? "PyScript module" : "HA automation YAML"));
  if (p.stmt_id) meta.push("Statement: $" + p.stmt_id);
  if (meta.length) {
    const m = document.createElement("p");
    m.className = "field-hint";
    m.textContent = meta.join(" · ");
    body.appendChild(m);
  }

  const tools = document.createElement("div");
  tools.className = "diag-tools";

  if (p.artifacts && p.artifacts.length) {
    const sel = document.createElement("select");
    p.artifacts.forEach((a, i) => {
      const o = document.createElement("option");
      o.value = a;
      o.textContent = (i === 0 ? "newest — " : "") + a;
      sel.appendChild(o);
    });
    const view = document.createElement("button");
    view.type = "button";
    view.className = "btn";
    view.textContent = "View generated code";
    const pre = document.createElement("pre");
    pre.className = "diag-code";
    pre.style.display = "none";
    view.addEventListener("click", async () => {
      const r = await fetch("/api/diagnostics/artifact/" + p.id + "/" + encodeURIComponent(sel.value));
      const d = await r.json();
      pre.textContent = d.content || d.error || "(empty)";
      pre.style.display = "";
    });
    tools.appendChild(sel);
    tools.appendChild(view);
    body.appendChild(tools);
    body.appendChild(pre);
  } else {
    const none = document.createElement("p");
    none.className = "field-hint";
    none.textContent = "No generated code kept yet — this piston hasn't compiled successfully.";
    body.appendChild(none);
    body.appendChild(tools);
  }

  if (p.status === "error") {
    const repair = document.createElement("button");
    repair.type = "button";
    repair.className = "btn btn-primary";
    repair.textContent = "Copy AI repair prompt";
    repair.title = "The failure + the compiler's input/output + the mapping file that " +
                   "governs this error — paste into an AI and it can hand back the edit";
    repair.addEventListener("click", async () => {
      const r = await fetch("/api/diagnostics/repair/" + p.id);
      const d = await r.json();
      if (!d.text) { repair.textContent = "Failed"; return; }
      await navigator.clipboard.writeText(d.text);
      repair.textContent = d.target
        ? "Copied — includes " + d.target.path.split("/").pop()
        : "Copied";
      setTimeout(() => (repair.textContent = "Copy AI repair prompt"), 3500);
    });
    tools.appendChild(repair);
  }

  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "btn";
  copy.textContent = "Copy debug info";
  copy.title = "Status + generated code + piston JSON, ready to paste into a chat or bug report";
  copy.addEventListener("click", async () => {
    const r = await fetch("/api/diagnostics/bundle/" + p.id);
    const d = await r.json();
    if (!d.text) { copy.textContent = "Failed"; return; }
    await navigator.clipboard.writeText(d.text);
    copy.textContent = "Copied — paste it anywhere";
    setTimeout(() => (copy.textContent = "Copy debug info"), 2500);
  });
  tools.appendChild(copy);

  // Compile-target override — the escape hatch for when the YAML translation
  // misbehaves (Jeremy 2026-07-19). Stored in PistonCore settings, never in
  // the piston JSON; changing it recompiles immediately.
  const bandWrap = document.createElement("span");
  bandWrap.className = "diag-band";
  const bandLabel = document.createElement("label");
  bandLabel.textContent = "Compile as ";
  const bandSel = document.createElement("select");
  [["auto", "Automatic (recommended)"],
   ["pyscript", "Always PyScript"],
   ["yaml", "HA automation only"]].forEach(([v, t]) => {
    const o = document.createElement("option");
    o.value = v; o.textContent = t;
    if ((p.band_pref || "auto") === v) o.selected = true;
    bandSel.appendChild(o);
  });
  bandSel.addEventListener("change", async () => {
    bandSel.disabled = true;
    const r = await fetch("/api/diagnostics/band/" + p.id + "?band=" + bandSel.value,
                          { method: "POST" });
    bandSel.disabled = false;
    if (r.ok) load();
  });
  bandLabel.appendChild(bandSel);
  bandWrap.appendChild(bandLabel);
  tools.appendChild(bandWrap);

  const openBtn = document.createElement("a");
  openBtn.className = "btn";
  openBtn.textContent = "Open piston";
  openBtn.href = "#";
  openBtn.addEventListener("click", (e) => {
    e.preventDefault();
    sessionStorage.setItem("pistoncore_open_piston", p.id);
    window.location.href = "/connect";
  });
  tools.appendChild(openBtn);

  wrap.appendChild(body);
  head.addEventListener("click", () => wrap.classList.toggle("open"));
  if (p.status === "error") wrap.classList.add("open");  // problems open by default
  return wrap;
}

async function load() {
  checksEl.innerHTML = '<div class="field-hint">Running checks…</div>';
  pistonsEl.innerHTML = "";
  const r = await fetch("/api/diagnostics");
  const d = await r.json();
  if (d.default_band) bandDefault.value = d.default_band;
  checksEl.innerHTML = "";
  d.checks.forEach((c) => checksEl.appendChild(checkRow(c)));
  const problems = d.pistons.filter((p) => p.status === "error");
  if (problems.length) {
    const b = document.createElement("div");
    b.className = "banner banner-error";
    b.textContent = problems.length + " piston" + (problems.length > 1 ? "s aren't" : " isn't") +
      " running in Home Assistant — they're opened below.";
    pistonsEl.appendChild(b);
  }
  d.pistons.forEach((p) => pistonsEl.appendChild(pistonRow(p)));
}

// instance-wide default compile target (per-piston overrides are on each row)
const bandDefault = document.getElementById("default_band");
bandDefault.addEventListener("change", async () => {
  bandDefault.disabled = true;
  const r = await fetch("/api/diagnostics/default-band?band=" + bandDefault.value,
                        { method: "POST" });
  bandDefault.disabled = false;
  document.getElementById("band-saved").textContent =
    r.ok ? "Saved — applies to pistons set to Automatic; re-save a piston to recompile it."
         : "Could not save.";
  if (r.ok) load();
});

document.getElementById("diag-refresh").addEventListener("click", load);
load();
