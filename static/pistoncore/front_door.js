function openPiston(id) {
  sessionStorage.setItem("pistoncore_open_piston", id);
  window.location.href = "/connect";
}

// Open webCoRE's own New-Piston dialog (blank / Duplicate / restore-by-code /
// import-backup-file — all four native creation paths) instead of the old
// name-prompt shortcut, which could only make blank pistons. The flag is
// consumed by dashboard/js/pistoncore-nav.js once the dashboard list page's
// session bootstrap finishes.
document.getElementById("new-piston").addEventListener("click", () => {
  sessionStorage.setItem("pistoncore_open_newpiston", "1");
  window.location.href = "/connect";
});

document.querySelectorAll(".piston-row").forEach((row) => {
  row.addEventListener("click", (e) => {
    e.preventDefault();
    openPiston(row.dataset.pistonId);
  });
});
