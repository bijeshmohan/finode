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

// Swap the From and To accounts in the simple transaction form.
document.body.addEventListener("click", (event) => {
  const button = event.target.closest("[data-swap-accounts]");
  if (!button) return;
  const form = button.closest("form");
  const from = form.querySelector('[name="from_account"]');
  const to = form.querySelector('[name="to_account"]');
  [from.value, to.value] = [to.value, from.value];
});

// ---- Add an account without leaving the transaction form ----
const NEW_ACCOUNT = "__new__";
let quickTarget = null;

function quickDialog() {
  return document.getElementById("quick-account");
}

function rememberAccountChoices() {
  document.querySelectorAll("select[data-account-select]").forEach((select) => {
    if (!("previous" in select.dataset)) select.dataset.previous = select.value;
  });
}

function suggestedRoot(select) {
  if (select.name === "to_account") return "Expenses";
  if (select.name === "from_account") return "Assets";
  const row = select.closest(".posting-row");
  return row && row.querySelector('[name="side"]').value === "debit" ? "Expenses" : "Assets";
}

// Opening balances only make sense for money you hold or owe.
function syncQuickBalance() {
  const dialog = quickDialog();
  const parent = dialog && dialog.querySelector('[name="parent_id"]');
  const field = dialog && dialog.querySelector("[data-balance-field]");
  if (!parent || !field) return;
  const root = parent.selectedOptions[0] && parent.selectedOptions[0].dataset.root;
  const show = root === "Assets" || root === "Liabilities";
  field.hidden = !show;
  field.querySelector("input").disabled = !show;
}

let quickOpening = false;

async function openQuickAccount(select) {
  quickTarget = select;
  quickOpening = true;
  try {
    await htmx.ajax("GET", `/app/accounts/quick?hint=${suggestedRoot(select)}`, {
      target: "#quick-account-body",
      swap: "innerHTML",
    });
  } catch (error) {
    // fall through: the form check below restores the picker
  }
  quickOpening = false;
  if (!quickDialog().querySelector("form")) {
    abandonQuickAccount();
    return;
  }
  syncQuickBalance();
  document.querySelectorAll(".toast").forEach((toast) => toast.remove());
  quickDialog().showModal();
}

// Put any picker left on "+ New account…" back to its last real choice.
function abandonQuickAccount() {
  document.querySelectorAll("select[data-account-select]").forEach((select) => {
    if (select.value === NEW_ACCOUNT) select.value = select.dataset.previous || "";
  });
  quickTarget = null;
}

function showToast(message) {
  document.querySelectorAll(".toast").forEach((toast) => toast.remove());
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.setAttribute("role", "status");
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

document.body.addEventListener("change", (event) => {
  const select = event.target;
  if (select.matches && select.matches("select[data-account-select]")) {
    select.classList.remove("needs-attention");
    if (select.value === NEW_ACCOUNT) openQuickAccount(select);
    else select.dataset.previous = select.value;
  } else if (select.matches && select.matches('#quick-account [name="parent_id"]')) {
    syncQuickBalance();
  }
});

document.body.addEventListener("click", (event) => {
  const dialog = quickDialog();
  if (event.target.closest("[data-quick-cancel]") || event.target === dialog) {
    abandonQuickAccount();
    dialog.close();
  }
});

// Esc and the Android back button fire "cancel" synchronously, before the dialog closes.
// "close" is delivered later, so it is only a fallback and must not touch a newer sheet.
document.addEventListener(
  "cancel",
  (event) => {
    if (event.target === quickDialog()) abandonQuickAccount();
  },
  true,
);
document.addEventListener(
  "close",
  (event) => {
    const dialog = quickDialog();
    if (event.target === dialog && !dialog.open && !quickOpening) abandonQuickAccount();
  },
  true,
);

document.body.addEventListener("account-added", async (event) => {
  const { aid, name } = event.detail;
  const response = await fetch("/app/accounts/options", { headers: { "HX-Request": "true" } });
  if (!response.ok) return;
  const options = await response.text();
  document.querySelectorAll("select[data-account-select]").forEach((select) => {
    const wanted = select === quickTarget ? aid : select.value;
    select.innerHTML = options;
    select.value = wanted;
    // A parent that just gained a sub-account can no longer be posted to.
    if (select.value !== wanted) {
      select.value = "";
      select.classList.add("needs-attention");
    }
    select.dataset.previous = select.value;
  });
  quickDialog().close();
  showToast(`Added ${name}`);
});

document.body.addEventListener("htmx:afterSwap", rememberAccountChoices);
document.addEventListener("DOMContentLoaded", rememberAccountChoices);
