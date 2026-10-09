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
  const currencySelect = document.querySelector('form [name="currency"]');
  document.querySelectorAll(".posting-row").forEach((row) => {
    // A row holding something other than the transaction's currency counts by its worth.
    const worth = row.querySelector('[name="value"]');
    const account = row.querySelector('select[name="account"]');
    const held = account && account.selectedOptions[0] ? account.selectedOptions[0].dataset.commodity : "";
    let text = worth && worth.value.trim() ? worth.value : null;
    if (text === null) {
      if (currencySelect && held && held !== currencySelect.value) return;
      text = row.querySelector('[name="amount"]').value;
    }
    const cents = toCents(text);
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

// Simple form: when From and To hold different things, open the "You receive" field and show the rate.
function heldBy(select) {
  const option = select && select.selectedOptions[0];
  return option ? option.dataset.commodity || "" : "";
}

function updateConversion() {
  const form = document.querySelector("form [data-conversion]");
  if (!form) return;
  const from = document.querySelector('[name="from_account"]');
  const to = document.querySelector('[name="to_account"]');
  const source = heldBy(from);
  const target = heldBy(to);
  const differs = source !== "" && target !== "" && source !== target;
  if (differs) form.open = true;
  const unit = form.querySelector("[data-receive-unit]");
  if (unit) unit.textContent = differs ? `in ${target}` : "in the account it goes to, when that holds something else";
  const hint = form.querySelector("[data-rate-hint]");
  if (!hint) return;
  const paid = parseFloat(document.querySelector('[name="amount"]').value.replace(/,/g, ""));
  const received = parseFloat(form.querySelector('[name="to_amount"]').value.replace(/,/g, ""));
  if (!(differs && paid > 0 && received > 0)) {
    hint.textContent = "";
    return;
  }
  // Quote the rate the way people say it: the smaller unit's price in the larger one (1 USD = 83.5 INR).
  const digits = { maximumSignificantDigits: 8 };
  hint.textContent =
    received >= paid
      ? `1 ${source} = ${(received / paid).toLocaleString(undefined, digits)} ${target}`
      : `1 ${target} = ${(paid / received).toLocaleString(undefined, digits)} ${source}`;
}

document.body.addEventListener("input", updateConversion);
document.body.addEventListener("change", updateConversion);
document.addEventListener("DOMContentLoaded", updateConversion);

// Swap the From and To accounts in the simple transaction form.
document.body.addEventListener("click", (event) => {
  const button = event.target.closest("[data-swap-accounts]");
  if (!button) return;
  const form = button.closest("form");
  const from = form.querySelector('[name="from_account"]');
  const to = form.querySelector('[name="to_account"]');
  [from.value, to.value] = [to.value, from.value];
  updateConversion();
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
    await htmx.ajax("GET", `/accounts/quick?hint=${suggestedRoot(select)}`, {
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
  const response = await fetch("/accounts/options", { headers: { "HX-Request": "true" } });
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

// Open the profile section named in the URL (#currency, #depth ...).
function openHashSection() {
  const target = location.hash ? document.getElementById(location.hash.slice(1)) : null;
  if (target && target.tagName === "DETAILS") target.open = true;
}
openHashSection();
window.addEventListener("hashchange", openHashSection);

// Theme override, remembered per browser in a cookie the server reads to avoid a flash.
function applyTheme(choice) {
  const root = document.documentElement;
  const chosen = choice === "light" || choice === "dark" ? choice : "auto";
  if (chosen === "auto") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", chosen);
  document.querySelectorAll("[data-theme-choice]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.themeChoice === chosen));
  });
  const label = document.querySelector("[data-theme-value]");
  if (label) label.textContent = { light: "Light", dark: "Dark" }[chosen] || "Match device";
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-theme-choice]");
  if (!button) return;
  const choice = button.dataset.themeChoice;
  document.cookie = `finode_theme=${choice}; path=/; max-age=31536000; samesite=lax`;
  applyTheme(choice);
});

applyTheme(document.documentElement.getAttribute("data-theme"));

// Copy buttons: data-copy names the element whose text is copied. Safari on iOS may refuse the
// clipboard API outside a plain tap, so fall back to selecting the text for the user to copy.
function selectText(element) {
  const range = document.createRange();
  range.selectNodeContents(element);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
}

async function copyText(source) {
  const text = source.textContent.trim();
  if (navigator.clipboard && window.isSecureContext) {
    try { await navigator.clipboard.writeText(text); return true; } catch (error) { /* try the fallback */ }
  }
  selectText(source);
  try { return document.execCommand("copy"); } catch (error) { return false; }
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  const source = document.querySelector(button.dataset.copy);
  if (!source) return;
  const label = button.dataset.label || button.textContent;
  button.dataset.label = label;
  const copied = await copyText(source);
  if (!copied) selectText(source);
  button.textContent = copied ? "Copied" : "Selected: press and hold to copy";
  setTimeout(() => { button.textContent = label; }, 2500);
});

// A freshly created token appears below the form: bring it into view (it is only shown once).
document.body.addEventListener("htmx:afterSwap", (event) => {
  const target = event.detail && event.detail.target;
  if (target && target.id === "new-token") target.scrollIntoView({ behavior: "smooth", block: "start" });
});

// Budget target form: the month field only applies to "by a month" targets.
function syncTargetKind() {
  const select = document.querySelector("select[data-target-kind]");
  const date = document.querySelector("label[data-target-date]");
  if (!select || !date) return;
  const show = select.value === "by_date";
  date.hidden = !show;
  date.querySelector("input").required = show;
}
document.addEventListener("change", (event) => {
  if (event.target.matches && event.target.matches("select[data-target-kind]")) syncTargetKind();
});
document.addEventListener("DOMContentLoaded", syncTargetKind);

// ---- One transaction form: simple by default, or split across accounts ----
function txnForm() {
  return document.querySelector("form[data-txn-form]");
}

function isSplit(form) {
  const toggle = form.querySelector("[data-split-toggle]");
  return !!toggle && toggle.checked;
}

function applyTxnMode(form) {
  const split = isSplit(form);
  form.classList.toggle("is-split", split);
  form.querySelectorAll("[data-section]").forEach((section) => {
    const hide = (section.dataset.section === "split") !== split;
    section.hidden = hide;
    // A hidden part must not be validated or sent.
    section.querySelectorAll("input, select, button").forEach((control) => {
      if (!control.hasAttribute("hx-get")) control.disabled = hide;
    });
  });
  updateBalanceStatus();
  updateConversion();
}

function fillSplitFromSimple(form) {
  const rows = form.querySelectorAll(".posting-row");
  if (rows.length < 2) return;
  const touched = [...rows].some((row) => row.querySelector('[name="amount"]').value.trim() || row.querySelector('select[name="account"]').value);
  if (touched) return;
  const paid = form.querySelector('[name="amount"]').value.trim();
  const received = form.querySelector('[name="to_amount"]').value.trim();
  const debit = rows[0];
  const credit = rows[1];
  debit.querySelector('select[name="account"]').value = form.querySelector('[name="to_account"]').value;
  debit.querySelector('[name="side"]').value = "debit";
  debit.querySelector('[name="amount"]').value = received || paid;
  credit.querySelector('select[name="account"]').value = form.querySelector('[name="from_account"]').value;
  credit.querySelector('[name="side"]').value = "credit";
  credit.querySelector('[name="amount"]').value = paid;
}

// Back to simple only when the rows are exactly one debit and one credit.
function fillSimpleFromSplit(form) {
  const used = [...form.querySelectorAll(".posting-row")].filter(
    (row) => row.querySelector('select[name="account"]').value || row.querySelector('[name="amount"]').value.trim()
  );
  if (used.length === 0) return true;
  if (used.length !== 2) return false;
  const [a, b] = used;
  const sides = [a.querySelector('[name="side"]').value, b.querySelector('[name="side"]').value];
  if (sides[0] === sides[1]) return false;
  const debit = sides[0] === "debit" ? a : b;
  const credit = debit === a ? b : a;
  const paid = credit.querySelector('[name="amount"]').value.trim();
  const received = debit.querySelector('[name="amount"]').value.trim();
  form.querySelector('[name="from_account"]').value = credit.querySelector('select[name="account"]').value;
  form.querySelector('[name="to_account"]').value = debit.querySelector('select[name="account"]').value;
  form.querySelector('[name="amount"]').value = paid;
  form.querySelector('[name="to_amount"]').value = received && received !== paid ? received : "";
  return true;
}

document.body.addEventListener("change", (event) => {
  const toggle = event.target.closest && event.target.closest("[data-split-toggle]");
  if (!toggle) return;
  const form = toggle.closest("form");
  const note = form.querySelector("[data-split-note]");
  if (note) note.textContent = "";
  if (toggle.checked) {
    fillSplitFromSimple(form);
  } else if (!fillSimpleFromSplit(form)) {
    toggle.checked = true;
    if (note) note.textContent = "Rows with more than two sides can't be shown as a simple transaction: remove the extra rows first.";
    return;
  }
  applyTxnMode(form);
});

// The form saves through the simple or the split route, whichever is showing.
document.body.addEventListener("htmx:configRequest", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || !form.matches("form[data-txn-form]")) return;
  event.detail.path = isSplit(form) ? form.dataset.postSplit : form.dataset.postSimple;
});

document.addEventListener("DOMContentLoaded", () => {
  const form = txnForm();
  if (form) applyTxnMode(form);
});
