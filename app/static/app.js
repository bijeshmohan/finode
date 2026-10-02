// Let htmx swap server-rendered validation messages (4xx) into the page.
document.body.addEventListener("htmx:beforeSwap", (event) => {
  const status = event.detail.xhr.status;
  if (status >= 400 && status < 500 && status !== 401) {
    event.detail.shouldSwap = true;
    event.detail.isError = false;
  }
});
