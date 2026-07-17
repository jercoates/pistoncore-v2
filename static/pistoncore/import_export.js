const banner = document.getElementById("import-banner");
const ta = document.getElementById("import-json");

function showBanner(kind, html) {
  banner.innerHTML = '<div class="banner banner-' + kind + '">' + html + "</div>";
}

document.getElementById("import-btn").addEventListener("click", async () => {
  const raw = ta.value.trim();
  if (!raw) { showBanner("info", "Paste some piston JSON first."); return; }
  const resp = await fetch("/api/import", { method: "POST", body: raw });
  const data = await resp.json();
  if (!resp.ok) {
    showBanner("info", "Import failed: " + (data.error || resp.status));
    return;
  }
  showBanner("success",
    'Imported "' + data.name + '" (' + data.statements + " statement" +
    (data.statements === 1 ? "" : "s") + ", paused). " +
    '<a href="/">Back to the piston list</a> to open it.');
  ta.value = "";
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
