function openPiston(id) {
  sessionStorage.setItem("pistoncore_open_piston", id);
  window.location.href = "/connect";
}

// Open webCoRE's own New-Piston dialog (blank / Duplicate / restore-by-code /
// import-backup-file — all four native creation paths). The flag is consumed
// by dashboard/js/pistoncore-nav.js once the list page's bootstrap finishes.
document.getElementById("new-piston").addEventListener("click", () => {
  sessionStorage.setItem("pistoncore_open_newpiston", "1");
  window.location.href = "/connect";
});

document.querySelectorAll(".piston-row").forEach((row) => {
  row.addEventListener("click", () => openPiston(row.dataset.pistonId));
});

// ── Per-row Pause/Enable (real shim endpoints; JSONP-wrapped body ignored) ──
document.querySelectorAll(".piston-toggle").forEach((btn) => {
  btn.addEventListener("click", async (e) => {
    e.stopPropagation();
    const row = btn.closest(".piston-row");
    const active = btn.dataset.active === "1";
    const action = active ? "pause" : "resume";
    btn.disabled = true;
    const resp = await fetch(`/intf/dashboard/piston/${action}?id=${row.dataset.pistonId}`);
    btn.disabled = false;
    if (!resp.ok) return;
    // JSONP body -> compile record -> live pill + loud banner (no refresh)
    try {
      const m = (await resp.text()).match(/^callback\((.*)\)$/s);
      const rec = m ? (JSON.parse(m[1]).compile || null) : null;
      if (rec) {
        const name = row.querySelector(".piston-name").textContent;
        const pill = row.querySelector(".compile-pill");
        const labels = { deployed: "deployed", error: "compile error",
                         pyscript: "needs PyScript", paused: "paused" };
        if (pill) {
          pill.className = "compile-pill compile-" + rec.status;
          pill.textContent = labels[rec.status] || rec.status;
          pill.title = rec.message || rec.file || rec.status;
        }
        const banner = document.getElementById("fd-banner");
        if (banner) {
          const ok = rec.status === "deployed";
          const cls = ok ? "banner-success" : (rec.status === "paused" ? "banner-info" : "banner-error");
          const text = ok
            ? "Compiled & deployed \"" + name + "\" -> " + rec.file + " (" + (rec.reload || "") + ")"
            : rec.status === "paused"
              ? "\"" + name + "\" paused - automation removed from HA"
              : "\"" + name + "\": " + (rec.message || rec.status);
          banner.innerHTML = '<div class="banner ' + cls + '"></div>';
          banner.firstChild.textContent = text;
        }
      }
    } catch (e) { /* banner is best-effort; the pill refresh on next load still tells the truth */ }
    const nowActive = !active;
    btn.dataset.active = nowActive ? "1" : "0";
    btn.textContent = nowActive ? "Pause" : "Enable";
    const dot = row.querySelector(".piston-enabled-dot");
    dot.classList.toggle("enabled", nowActive);
    dot.classList.toggle("disabled", !nowActive);
    dot.title = nowActive ? "Active" : "Paused";
  });
});

// ── Folder filter + search (client-side, search scoped to current folder) ──
const rows = Array.from(document.querySelectorAll(".piston-row"));
const search = document.getElementById("fd-search");
const folderTitle = document.getElementById("fd-folder-title");
const empty = document.getElementById("fd-empty");
let activeFolder = "all";

function applyFilter() {
  const q = (search?.value || "").trim().toLowerCase();
  let shown = 0;
  rows.forEach((row) => {
    const inFolder = activeFolder === "all" || row.dataset.category === activeFolder;
    const matches = !q || row.dataset.search.includes(q);
    const show = inFolder && matches;
    row.style.display = show ? "" : "none";
    if (show) shown++;
  });
  if (empty) empty.style.display = shown ? "none" : "";
}

document.querySelectorAll(".folder-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".folder-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    activeFolder = btn.dataset.folder;
    folderTitle.textContent = btn.textContent.replace(/\d+\s*$/, "").trim();
    applyFilter();
  });
});
if (search) search.addEventListener("input", applyFilter);
