document.getElementById("settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const params = new URLSearchParams({
    ha_url: form.ha_url.value,
    ha_token: form.ha_token.value,
  });
  const resp = await fetch("/api/settings?" + params.toString(), { method: "POST" });
  if (!resp.ok) {
    alert("Could not save settings.");
    return;
  }
  window.location.href = "/settings?saved=1";
});
