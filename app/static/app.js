// Let htmx swap server-rendered validation messages (4xx) into the page.
document.body.addEventListener("htmx:beforeSwap", (event) => {
  const status = event.detail.xhr.status;
  if (status >= 400 && status < 500 && status !== 401) {
    event.detail.shouldSwap = true;
    event.detail.isError = false;
  }
});

// Live debit/credit balance indicator for the split transaction form.
// Amounts are handled as integer cents to avoid floating point errors.
function toCents(text) {
  const match = /^(\d*)(?:\.(\d*))?$/.exec(text.replace(/[,\s]/g, ""));
  if (!match || (match[1] === "" && !match[2])) return null;
  const whole = parseInt(match[1] || "0", 10);
  const fraction = parseInt((match[2] || "").padEnd(2, "0").slice(0, 2), 10);
  return whole * 100 + fraction;
}

function formatCents(cents) {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  const whole = Math.floor(abs / 100).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${sign}${whole}.${String(abs % 100).padStart(2, "0")}`;
}

function updateBalanceStatus() {
  const status = document.getElementById("balance-status");
  if (!status) return;
  let debit = 0;
  let credit = 0;
  document.querySelectorAll(".posting-row").forEach((row) => {
    const cents = toCents(row.querySelector('[name="amount"]').value);
    if (cents === null) return;
    if (row.querySelector('[name="side"]').value === "debit") debit += cents;
    else credit += cents;
  });
  const diff = debit - credit;
  status.classList.toggle("ok", diff === 0 && debit > 0);
  status.classList.toggle("off", diff !== 0);
  status.textContent =
    diff === 0
      ? `Balanced · debits ${formatCents(debit)} = credits ${formatCents(credit)}`
      : `Unbalanced by ${formatCents(Math.abs(diff))} · debits ${formatCents(debit)}, credits ${formatCents(credit)}`;
}

document.body.addEventListener("input", updateBalanceStatus);
document.body.addEventListener("change", updateBalanceStatus);
document.body.addEventListener("htmx:afterSwap", updateBalanceStatus);
document.body.addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove-row]");
  if (!button) return;
  const rows = document.querySelectorAll(".posting-row");
  if (rows.length > 2) button.closest(".posting-row").remove();
  updateBalanceStatus();
});
document.addEventListener("DOMContentLoaded", updateBalanceStatus);
