/* Somente interação de formulários. A leitura e todos os cálculos são Python. */
document.documentElement.classList.add("enhanced");
document.querySelectorAll(".autosubmit").forEach(select => {
  select.addEventListener("change", () => select.form.requestSubmit());
});
const form = document.getElementById("upload-form");
const input = document.getElementById("file");
const zone = document.getElementById("dropzone");
const status = document.getElementById("upload-status");
if (form && input && zone) {
  zone.addEventListener("dragover", event => {
    event.preventDefault();
    zone.classList.add("dragging");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragging"));
  zone.addEventListener("drop", event => {
    event.preventDefault();
    zone.classList.remove("dragging");
    if (event.dataTransfer.files.length !== 1) {
      status.textContent = "Importe um arquivo por vez.";
      return;
    }
    input.files = event.dataTransfer.files;
    status.textContent = "Arquivo selecionado: " + input.files[0].name;
  });
  form.addEventListener("submit", () => {
    status.textContent = "Analisando a planilha em Python. Aguarde…";
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    button.textContent = "Analisando…";
  });
}

