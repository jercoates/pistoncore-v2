function openPiston(id) {
  sessionStorage.setItem("pistoncore_open_piston", id);
  window.location.href = "/connect";
}

document.getElementById("new-piston").addEventListener("click", async () => {
  const name = prompt("Piston name:", "New Piston");
  if (name === null) return;

  const params = new URLSearchParams({ name: name || "New Piston" });
  const resp = await fetch("/api/new-piston?" + params.toString(), { method: "POST" });
  if (!resp.ok) {
    alert("Could not create piston.");
    return;
  }
  const data = await resp.json();
  openPiston(data.id);
});

document.querySelectorAll(".piston-row").forEach((row) => {
  row.addEventListener("click", (e) => {
    e.preventDefault();
    openPiston(row.dataset.pistonId);
  });
});
