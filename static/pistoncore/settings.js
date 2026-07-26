const form = document.getElementById("settings-form");

function settingsParams() {
  // media config is a JSON blob the backend MERGES, so send only what's set —
  // an empty server_base would otherwise blank the auto-detected address.
  const media = {};
  if (form.media_server_base && form.media_server_base.value.trim()) {
    media.server_base = form.media_server_base.value.trim();
  }
  return new URLSearchParams({
    ha_url: form.ha_url.value,
    ha_token: form.ha_token.value,
    write_mode: form.write_mode.value,
    ha_config_path: form.ha_config_path.value,
    smb_host: form.smb_host.value,
    smb_share: form.smb_share.value,
    smb_username: form.smb_username.value,
    smb_password: form.smb_password.value,
    tts_engine: form.tts_engine ? form.tts_engine.value : "",
    media: JSON.stringify(media),
  });
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const resp = await fetch("/api/settings?" + settingsParams().toString(), { method: "POST" });
  if (!resp.ok) {
    alert("Could not save settings.");
    return;
  }
  window.location.href = "/settings?saved=1";
});

// write-mode field toggle
const modeSel = document.getElementById("write_mode");
function syncMode() {
  document.getElementById("local-fields").style.display = modeSel.value === "smb" ? "none" : "";
  document.getElementById("smb-fields").style.display = modeSel.value === "smb" ? "" : "none";
}
modeSel.addEventListener("change", syncMode);
syncMode();

// "Test write target": saves current fields first, then probes, so the test
// always runs against what's on screen — a failed probe is loud, not silent.
document.getElementById("test-write").addEventListener("click", async () => {
  const banner = document.getElementById("write-test-banner");
  banner.innerHTML = '<div class="banner banner-info">Testing…</div>';
  await fetch("/api/settings?" + settingsParams().toString(), { method: "POST" });
  const resp = await fetch("/api/settings/test-write", { method: "POST" });
  const data = await resp.json();
  banner.innerHTML = resp.ok
    ? '<div class="banner banner-success">Write target OK — ' + data.target + "</div>"
    : '<div class="banner banner-info">' + (data.error || "Test failed.") + "</div>";
});

// configuration.yaml include-lines (analyze -> show exact changes -> consent click)
const cyBanner = document.getElementById("config-yaml-banner");
const cyChanges = document.getElementById("config-yaml-changes");
const cyList = document.getElementById("config-yaml-list");

function cyShow(kind, msg) {
  cyBanner.innerHTML = '<div class="banner banner-' + kind + '">' + msg + "</div>";
}

document.getElementById("config-yaml-check").addEventListener("click", async () => {
  cyChanges.style.display = "none";
  cyShow("info", "Checking…");
  // make sure the probe target matches what's on screen
  await fetch("/api/settings?" + settingsParams().toString(), { method: "POST" });
  const resp = await fetch("/api/config-yaml");
  const data = await resp.json();
  if (!resp.ok) { cyShow("info", data.error || "Check failed."); return; }
  if (data.status === "ok") { cyShow("success", data.message); return; }
  cyList.innerHTML = "";
  (data.changes || []).forEach((c) => {
    const li = document.createElement("li"); li.textContent = c; cyList.appendChild(li);
  });
  (data.refusals || []).forEach((r) => {
    const li = document.createElement("li"); li.textContent = "⚠ " + r; cyList.appendChild(li);
  });
  if ((data.changes || []).length) {
    cyShow("info", "Proposed changes (a timestamped backup is written before applying):");
    cyChanges.style.display = "";
  } else {
    cyShow("info", "Cannot auto-edit:");
    cyChanges.style.display = "";
    document.getElementById("config-yaml-apply").style.display = "none";
  }
});

document.getElementById("config-yaml-apply").addEventListener("click", async () => {
  cyShow("info", "Applying…");
  const resp = await fetch("/api/config-yaml/apply", { method: "POST" });
  const data = await resp.json();
  if (!resp.ok) { cyShow("info", data.error || "Apply failed."); return; }
  cyChanges.style.display = "none";
  cyShow("success", (data.applied || []).join("; ") +
    ". Backup: " + (data.backup || "n/a") +
    '. <button type="button" class="btn" id="reload-yaml">Reload HA YAML now</button>');
  document.getElementById("reload-yaml").addEventListener("click", async () => {
    cyShow("info", "Reloading HA YAML configuration…");
    const r = await fetch("/api/ha/reload-yaml", { method: "POST" });
    const d = await r.json();
    cyShow(r.ok ? "success" : "info", r.ok
      ? "HA reloaded its YAML. Check that your automations list still looks right. " +
        "If PistonCore items ever fail to appear after a reload, use a full restart " +
        "(HA Settings → System → Restart)."
      : (d.error || "Reload failed — restart HA manually (Settings → System → Restart)."));
  });
});

/* ── Translation data: update, import, restore ────────────────────────────
   The relief valve. A user with no maintainer upstream has to be able to pull
   in a fix, try it, and back it out — without editing files or running
   commands. Every path here previews before it writes and can be undone. */

const trBanner = document.getElementById("tr-banner");
const trPreview = document.getElementById("tr-preview");
const trList = document.getElementById("tr-list");
const trWarning = document.getElementById("tr-warning");
let trPending = null;                       // {source, url} awaiting confirmation

function trShow(kind, html) {
  trBanner.innerHTML = '<div class="banner banner-' + kind + '">' + html + "</div>";
}

function trHidePreview() {
  trPreview.style.display = "none";
  trWarning.innerHTML = "";
  trPending = null;
}

async function trFetch(path, body) {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return { ok: resp.ok, data: await resp.json() };
}

async function trCheck(source, url) {
  trHidePreview();
  trShow("info", "Looking…");
  const { ok, data } = await trFetch("/api/translation/preview", { source, url });
  if (!ok) { trShow("error", data.error || "That didn't work."); return; }
  if (!data.any_change) {
    trShow("success", "Nothing to do — you already have everything from that source.");
    return;
  }
  trList.innerHTML = "";
  (data.changes || []).forEach((c) => {
    if (c.state === "unchanged") return;
    const li = document.createElement("li");
    li.textContent = c.file + " — " + (c.state === "new" ? "new file" : "would change")
      + (c.risky ? "  ⚠ template" : "");
    trList.appendChild(li);
  });
  if (data.risky) {
    /* Loud, but never a block: the user chooses (Jeremy's rule). */
    trWarning.innerHTML =
      '<div class="banner banner-error"><strong>Careful — this includes templates.</strong> ' +
      "Templates are closer to program code than to data: they run as part of your " +
      "compiler. Only import these from somewhere you actually trust. The data-only " +
      "files (the <code>.json</code> ones) don't carry this risk.</div>";
  }
  trShow("info", "Nothing has been changed yet. What's currently in place will be saved "
    + "first, so you can go back.");
  trPending = { source, url };
  trPreview.style.display = "";
}

document.getElementById("tr-official").addEventListener("click", () => trCheck("official", ""));

document.getElementById("tr-check-link").addEventListener("click", () => {
  const url = document.getElementById("tr-url").value.trim();
  if (!url) { trShow("error", "Paste a link first."); return; }
  trCheck("link", url);
});

document.getElementById("tr-cancel").addEventListener("click", () => {
  trHidePreview();
  trShow("info", "Cancelled — nothing was changed.");
});

document.getElementById("tr-apply").addEventListener("click", async () => {
  if (!trPending) return;
  trShow("info", "Importing…");
  const { ok, data } = await trFetch("/api/translation/apply", trPending);
  if (!ok) { trShow("error", data.error || "Import failed — nothing was changed."); return; }
  trHidePreview();
  trShow("success", "Imported " + (data.written || []).length + " file(s). "
    + "Recompile a piston to use it. Use <strong>Go back</strong> below if it "
    + "misbehaves. <a href='/settings'>Refresh this page</a> to see the new version.");
});

document.querySelectorAll(".tr-restore").forEach((btn) => {
  btn.addEventListener("click", async () => {
    trHidePreview();
    trShow("info", "Restoring…");
    const { ok, data } = await trFetch("/api/translation/restore",
                                       { which: btn.dataset.which });
    if (!ok) { trShow("error", data.error || "Restore failed — nothing was changed."); return; }
    trShow("success", "Restored " + data.restored + " (" + (data.written || []).length
      + " file(s)). <a href='/settings'>Refresh this page</a> to see it.");
  });
});
