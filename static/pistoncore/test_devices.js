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
      if (res.error) { banner("warning", res.error); }
      else { load(); }
    };
    addEl.style.display = "none"; listEl.innerHTML = ""; return;
  }
  statusEl.innerHTML = "";
  addEl.style.display = "";
  renderDevices(data.devices || []);
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
    case "sensor": case "number":
      return [capRow(e.name, [numberBox(e, st, null, "any")], st + (a.unit_of_measurement ? " " + a.unit_of_measurement : ""))];
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
