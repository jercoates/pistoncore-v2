const banner = document.getElementById("import-banner");
const ta = document.getElementById("import-json");

function showBanner(kind, html) {
  banner.innerHTML = '<div class="banner banner-' + kind + '">' + html + "</div>";
}

document.getElementById("import-btn").addEventListener("click", () => {
  const raw = ta.value.trim();
  if (!raw) { showBanner("info", "Paste some piston JSON first."); return; }
  let data;
  try { data = JSON.parse(raw); } catch (e) {
    showBanner("info", "Not valid JSON: " + e.message); return;
  }
  const piston = (data && typeof data.piston === "object") ? data.piston : data;
  const name = (data && (data.name || (data.meta && data.meta.name))) || "Imported Piston";
  if (!piston || typeof piston !== "object" || !("s" in piston || "o" in piston || "v" in piston)) {
    showBanner("info", "JSON has neither a 'piston' key nor piston-shaped keys (o/r/s/v)."); return;
  }
  // Hand off to webCoRE's OWN import flow (Rebuild-piston-items device remap) —
  // devices get mapped to real ones BEFORE anything is saved, so raw hash IDs
  // can never appear anywhere (house rule: users see only friendly names).
  sessionStorage.setItem("pistoncore_stage_import", JSON.stringify({ name: name, piston: piston }));
  window.location.href = "/connect";
});

// drag-and-drop a .json file onto the textarea
["dragover", "dragenter"].forEach((ev) =>
  ta.addEventListener(ev, (e) => { e.preventDefault(); }));
ta.addEventListener("drop", (e) => {
  e.preventDefault();
  const file = e.dataTransfer.files && e.dataTransfer.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => { ta.value = reader.result; };
  reader.readAsText(file);
});

// export
const exportBtn = document.getElementById("export-btn");
if (exportBtn) {
  const out = document.getElementById("export-out");
  const copyBtn = document.getElementById("copy-btn");
  exportBtn.addEventListener("click", async () => {
    const id = document.getElementById("export-select").value;
    const resp = await fetch("/api/export/" + id);
    if (!resp.ok) { out.style.display = "block"; out.textContent = "Export failed."; return; }
    const data = await resp.json();
    out.textContent = JSON.stringify(data, null, 2);
    out.style.display = "block";
    copyBtn.style.display = "";
  });
  copyBtn.addEventListener("click", async () => {
    await navigator.clipboard.writeText(out.textContent);
    copyBtn.textContent = "Copied!";
    setTimeout(() => (copyBtn.textContent = "Copy to clipboard"), 1500);
  });
}
