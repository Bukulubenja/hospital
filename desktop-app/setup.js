const input = document.getElementById("url");
const errorEl = document.getElementById("error");

document.getElementById("continue").addEventListener("click", () => {
  const value = input.value.trim();

  if (!/^https?:\/\/.+/.test(value)) {
    errorEl.textContent = "Enter a full address starting with http:// or https://";
    return;
  }

  window.hms.saveHospitalUrl(value);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    document.getElementById("continue").click();
  }
});
