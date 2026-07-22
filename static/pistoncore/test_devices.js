// Test Devices panel (VIRTUAL_DEVICES_SPEC.md Stage 4). Talks only to
// PistonCore's own /api/test-devices/* endpoints, which drive the forked
// `virtual` integration on HA and read live state back. No device state is kept
// here — every control reloads the list so what you see is HA's truth.

const listEl = document.getElementById("td-list");
const statusEl = document.getElementById("td-status");
const addEl = document.getElementById("td-add");
const typeSel = document.getElementById("td-type");
const nameInput = document.getElementById("td-name");

const el = (tag, cls) => { const n = document.createElement(tag); if (cls) n.className = cls; return n; };
const banner = (kind, html) => { statusEl.innerHTML = `<div class="banner banner-${kind}">${html}</div>`; };

async function api(path, body) {
  const opts = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  const r = await fetch(path, opts);
  return r.json().catch(() => ({}));
}

// Offer to install the integration into HA — GATED behind a warning the user
// must acknowledge (the Install button stays disabled until the box is ticked,
// and the backend also requires the acknowledgment, so it can't be skipped).
function showInstall() {
  statusEl.innerHTML =
    "<div class='banner banner-warning'>" +
    "<strong>Install the test-device integration onto Home Assistant?</strong>" +
    "<div class='field-hint' style='margin-top:6px'>PistonCore will <strong>write files into your " +
    "Home Assistant</strong> (<code>custom_components/virtual/</code>) and then <strong>restart Home " +
    "Assistant</strong> — it will be offline for roughly 30–60 seconds. Your existing automations, " +
    "scripts, and settings are not touched. (Prefer HACS? You can install it that way instead and " +
    "skip this.)</div>" +
    "<label class='td-switch' style='margin-top:10px'><input type='checkbox' id='td-inst-ack'> " +
    "I understand PistonCore will write into my Home Assistant and restart it.</label>" +
    "<div style='margin-top:10px'><button class='btn btn-primary' id='td-install' disabled>" +
    "Install onto Home Assistant</button></div></div>";
  const ack = document.getElementById("td-inst-ack");
  const btn = document.getElementById("td-install");
  ack.onchange = () => { btn.disabled = !ack.checked; };
  btn.onclick = async () => {
    btn.disabled = true; btn.textContent = "Writing files…";
    const res = await api("/api/test-devices/install", { acknowledged: true });
    if (res.error) { banner("error", res.error); return; }
    statusEl.innerHTML =
      "<div class='banner banner-info'>Files written — Home Assistant is restarting to load the " +
      "integration (about 30–60 seconds). When it's back, click below.<div style='margin-top:10px'>" +
      "<button class='btn btn-primary' id='td-after'>Continue setup</button></div></div>";
    document.getElementById("td-after").onclick = async () => {
      const b = document.getElementById("td-after");
      b.disabled = true; b.textContent = "Setting up…";
      const r = await api("/api/test-devices/setup", {});
      if (r.error) {
        banner("warning", r.error + " (Home Assistant may still be restarting — wait a moment and click Set up again.)");
      } else { load(); }
    };
  };
}

async function load() {
  const data = await api("/api/test-devices/list");
  if (typeSel && !typeSel.dataset.filled && data.types) {
    typeSel.innerHTML = data.types.map((t) => `<option>${t}</option>`).join("");
    typeSel.dataset.filled = "1";
  }
  if (!data.configured) {
    banner("info", "Connect PistonCore to Home Assistant in <a href='/settings'>Settings</a> first.");
    addEl.style.display = "none"; listEl.innerHTML = ""; return;
  }
  if (!data.present) {
    statusEl.innerHTML =
      "<div class='banner banner-info'>Test devices need a one-time setup on Home Assistant. " +
      "<button class='btn btn-primary' id='td-setup'>Set up test devices</button>" +
      "<div class='field-hint' style='margin-top:8px'>Creates a “PistonCore Test Devices” group " +
      "in Home Assistant. If the test-device integration isn’t installed yet, you’ll be told how.</div></div>";
    document.getElementById("td-setup").onclick = async () => {
      const b = document.getElementById("td-setup");
      b.disabled = true; b.textContent = "Setting up…";
      const res = await api("/api/test-devices/setup", {});
      if (res.error && /isn.t installed|not installed/i.test(res.error)) { showInstall(); }
      else if (res.error) { banner("warning", res.error); b.disabled = false; b.textContent = "Set up test devices"; }
      else { load(); }
    };
    addEl.style.display = "none"; listEl.innerHTML = ""; return;
  }
  statusEl.innerHTML = "";
  addEl.style.display = "";
  renderDevices(data.devices || []);
  loadClones();
}

// Clone panel (user-facing): faithful copies of the user's REAL devices.
async function loadClones() {
  const wrap = document.getElementById("td-clone-wrap");
  const list = document.getElementById("td-clone-list");
  const data = await api("/api/test-devices/discover");
  const types = data.types || [];
  if (!types.length) { wrap.style.display = "none"; return; }
  wrap.style.display = "";
  list.innerHTML = "";
  types.forEach((t) => {
    const row = el("div", "td-clone-row");
    const info = el("div", "td-clone-info");
    const name = el("span", "td-clone-name");
    name.textContent = t.label + (t.count > 1 ? `  (×${t.count})` : "");
    const caps = el("span", "td-clone-caps");
    caps.textContent = t.caps.join(" · ");
    caps.title = t.caps.join(", ");
    info.append(name, caps);
    const btn = el("button", "btn");
    btn.textContent = "Clone";
    btn.onclick = async () => {
      btn.disabled = true; btn.textContent = "Cloning…";
      const res = await api("/api/test-devices/create-twin", { label: t.label, entities: t.entities });
      if (res.error) { banner("error", res.error); btn.disabled = false; btn.textContent = "Clone"; return; }
      load();
    };
    row.append(info, btn);
    list.appendChild(row);
  });
}

function renderDevices(devices) {
  listEl.innerHTML = "";
  if (!devices.length) {
    const p = el("p", "td-empty");
    p.textContent = "No test devices yet — add one above.";
    listEl.appendChild(p);
    return;
  }
  devices.forEach((d) => listEl.appendChild(renderRow(d)));
}

function renderRow(d) {
  const row = el("div", "td-row");
  const head = el("div", "td-row-head");
  const tag = el("span", "td-tag"); tag.textContent = "Test";
  const name = el("span", "td-name"); name.textContent = d.device_name;
  const rm = el("button", "btn td-remove"); rm.textContent = "Remove";
  rm.onclick = async () => { rm.disabled = true; await api("/api/test-devices/remove", { name: d.device_name }); load(); };
  head.append(tag, name, rm);
  row.appendChild(head);

  const caps = el("div", "td-caps");
  d.entities.forEach((e) => controlsFor(e).forEach((c) => caps.appendChild(c)));
  row.appendChild(caps);
  return row;
}

// A labeled capability row: label + control(s) + live-state readout.
function capRow(label, controlNodes, stateText) {
  const cap = el("div", "td-cap");
  const l = el("span", "td-cap-label"); l.textContent = label;
  const ctrl = el("span", "td-cap-control");
  controlNodes.forEach((n) => ctrl.appendChild(n));
  if (stateText !== undefined && stateText !== null && stateText !== "") {
    const s = el("span", "td-state"); s.textContent = `now: ${stateText}`;
    ctrl.appendChild(s);
  }
  cap.append(l, ctrl);
  return cap;
}

async function set(entity_id, value, sub) {
  await api("/api/test-devices/set", { entity_id, value, sub });
  load();
}

function toggle(e, onVal, offVal, checked) {
  const cb = el("input"); cb.type = "checkbox"; cb.checked = checked;
  cb.onchange = () => set(e.entity_id, cb.checked ? onVal : offVal);
  return cb;
}
function selectOf(e, options, current, sub) {
  const s = el("select");
  s.innerHTML = options.map((o) => `<option ${o === current ? "selected" : ""}>${o}</option>`).join("");
  s.onchange = () => set(e.entity_id, s.value, sub);
  return s;
}
function numberBox(e, current, sub, step) {
  const n = el("input"); n.type = "number"; if (step) n.step = step;
  if (current !== undefined && current !== null) n.value = current;
  n.onchange = () => set(e.entity_id, n.value, sub);
  return n;
}
function textBox(e, current, sub) {
  const n = el("input"); n.type = "text"; n.placeholder = "type a value…";
  if (current !== undefined && current !== null) n.value = current;
  n.onchange = () => set(e.entity_id, n.value, sub);
  return n;
}

// Build the control(s) for one entity, keyed by its HA domain.
function controlsFor(e) {
  const a = e.attributes || {};
  const st = e.state;
  switch (e.domain) {
    case "binary_sensor":
      return [capRow(e.name, [toggle(e, "on", "off", st === "on")], st)];
    case "switch": case "light": case "fan": case "siren":
      return [capRow(e.name, [toggle(e, "on", "off", st === "on")], st)];
    case "lock":
      return [capRow(e.name, [toggle(e, "unlocked", "locked", st === "unlocked")], st)];
    case "cover":
      return [capRow(e.name, [toggle(e, "open", "closed", st === "open")], st)];
    case "sensor":
      // sensors can hold strings (a camera's smartDetectType = "person") or
      // numbers (lux = 500) — free text handles both; you type the value.
      return [capRow(e.name, [textBox(e, st)], st + (a.unit_of_measurement ? " " + a.unit_of_measurement : ""))];
    case "number":
      return [capRow(e.name, [numberBox(e, st, null, "any")], st)];
    case "alarm_control_panel":
      return [capRow(e.name, [selectOf(e, ["disarmed", "armed_home", "armed_away", "armed_night", "armed_vacation", "triggered"], st)], st)];
    case "vacuum":
      return [capRow(e.name, [selectOf(e, ["docked", "cleaning", "paused", "returning", "idle"], st)], st)];
    case "humidifier":
      return [
        capRow(e.name, [toggle(e, "on", "off", st === "on")], st),
        capRow(e.name + " — target %", [numberBox(e, a.humidity, "humidity", "1")], a.humidity),
      ];
    case "climate":
      return [
        capRow(e.name + " — mode", [selectOf(e, ["off", "heat", "cool", "heat_cool", "auto"], st, "mode")], st),
        capRow(e.name + " — target °", [numberBox(e, a.temperature, "temperature", "0.5")], a.temperature),
        capRow(e.name + " — current °", [numberBox(e, a.current_temperature, "current_temperature", "0.5")], a.current_temperature),
      ];
    case "media_player":
      return [
        capRow(e.name + " — state", [selectOf(e, ["off", "on", "idle", "playing", "paused"], st, "state")], st),
        capRow(e.name + " — volume", [volumeSlider(e, a.volume_level)], a.volume_level),
      ];
    case "button": {
      const b = el("button", "btn"); b.textContent = "Press";
      b.onclick = () => set(e.entity_id, "press");
      return [capRow(e.name, [b], st)];
    }
    case "event": {
      // button / scene / multi-tap: pick an event type and fire it
      const types = (a.event_types && a.event_types.length)
        ? a.event_types : ["press", "double_press", "hold", "release"];
      const sel = el("select");
      sel.innerHTML = types.map((t) => `<option>${t}</option>`).join("");
      const b = el("button", "btn"); b.textContent = "Fire";
      b.onclick = () => set(e.entity_id, sel.value);
      return [capRow(e.name, [sel, b], a.event_type || "—")];
    }
    default:
      return [capRow(e.name, [], st)];
  }
}

function volumeSlider(e, current) {
  const r = el("input"); r.type = "range"; r.min = "0"; r.max = "1"; r.step = "0.05";
  if (current !== undefined && current !== null) r.value = current;
  r.onchange = () => set(e.entity_id, parseFloat(r.value), "volume");
  return r;
}

document.getElementById("td-create").onclick = async () => {
  const name = nameInput.value.trim();
  if (!name) { nameInput.focus(); return; }
  const btn = document.getElementById("td-create");
  btn.disabled = true;
  const res = await api("/api/test-devices/create", { type: typeSel.value, name });
  btn.disabled = false;
  if (res.error) { banner("error", res.error); return; }
  nameInput.value = "";
  load();
};

load();
