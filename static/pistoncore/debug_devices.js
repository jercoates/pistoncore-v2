// Debug Library (developer surface, VIRTUAL_DEVICES_SPEC §5.8). Lists every
// webCoRE capability as a single settable test type, generated server-side from
// the vocab. Adding one (or the whole suite) creates it via the same integration
// the clone panel uses; drive them on /test-devices.

const grid = document.getElementById("dbg-grid");
const statusEl = document.getElementById("dbg-status");
const actions = document.getElementById("dbg-actions");
const countEl = document.getElementById("dbg-count");
const unmapEl = document.getElementById("dbg-unmappable");

const el = (t, c) => { const n = document.createElement(t); if (c) n.className = c; return n; };
const banner = (k, h) => { statusEl.innerHTML = `<div class="banner banner-${k}">${h}</div>`; };

async function api(path, body) {
  const opts = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
  return (await fetch(path, opts)).json().catch(() => ({}));
}

async function load() {
  const lib = await api("/api/test-devices/debug-library");
  const types = lib.types || [];
  countEl.textContent = `${types.length} testable device types`;
  actions.style.display = "";
  grid.innerHTML = "";
  types.forEach((t) => {
    const card = el("div", "dbg-card");
    const main = el("div", "dbg-card-main");
    const name = el("span", "dbg-name"); name.textContent = t.label;
    const map = el("span", "dbg-map"); map.textContent = t.domain + (t.device_class ? " / " + t.device_class : "");
    main.append(name, map);
    const btn = el("button", "btn btn-sm"); btn.textContent = "Add";
    btn.onclick = async () => {
      btn.disabled = true; btn.textContent = "Adding…";
      const res = await api("/api/test-devices/debug-add", { label: t.label, entities: t.entities });
      if (res.error) { banner("error", res.error); btn.disabled = false; btn.textContent = "Add"; return; }
      btn.textContent = "Added ✓";
    };
    card.append(main, btn);
    grid.appendChild(card);
  });

  const unmap = lib.unmappable || [];
  if (unmap.length) {
    unmapEl.innerHTML = `<p class="dbg-unmap"><strong>${unmap.length}</strong> capabilities can't be reproduced yet — `
      + unmap.map((u) => `${u.label} <code>(${u.why})</code>`).join(" · ") + "</p>";
  }
}

document.getElementById("dbg-suite").onclick = async () => {
  const b = document.getElementById("dbg-suite");
  if (!confirm("Create a test device for every capability in the suite? This adds a lot of devices to Home Assistant (you can remove them on the Test Devices panel).")) return;
  b.disabled = true; b.textContent = "Spinning up… (this takes a bit)";
  const res = await api("/api/test-devices/debug-suite", {});
  b.disabled = false; b.textContent = "Spin up the whole suite";
  if (res.error) { banner("error", res.error); return; }
  banner("success", `Created ${res.created} test devices — drive them on the <a href="/test-devices">Test Devices</a> panel.`);
};

load();
