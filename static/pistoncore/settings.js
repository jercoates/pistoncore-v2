const form = document.getElementById("settings-form");

function settingsParams() {
  return new URLSearchParams({
    ha_url: form.ha_url.value,
    ha_token: form.ha_token.value,
    write_mode: form.write_mode.value,
    ha_config_path: form.ha_config_path.value,
    smb_host: form.smb_host.value,
    smb_share: form.smb_share.value,
    smb_username: form.smb_username.value,
    smb_password: form.smb_password.value,
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
