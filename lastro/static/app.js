document.addEventListener("htmx:beforeSwap", (event) => {
  if ([422, 413].includes(event.detail.xhr.status)) {
    event.detail.shouldSwap = true;
    event.detail.isError = false;
  }
});

document.addEventListener("htmx:afterSwap", () => {
  document.getElementById("falha-rede").hidden = true;
  document.getElementById("resultado").focus();
});

document.addEventListener("htmx:sendError", () => {
  document.getElementById("falha-rede").hidden = false;
});

document.addEventListener("htmx:responseError", () => {
  document.getElementById("falha-rede").hidden = false;
});
