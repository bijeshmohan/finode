// Let htmx swap server-rendered validation messages (4xx) into the page.
document.body.addEventListener("htmx:beforeSwap", (event) => {
  const status = event.detail.xhr.status;
  if (status >= 400 && status < 500 && status !== 401) {
    event.detail.shouldSwap = true;
    event.detail.isError = false;
  }
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
  const row = select.closest("[data-row]");
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

// ---- The transaction form: a total, then rows on each side until both sides add up to it ----
// Amounts are BigInts with 8 decimals (the most the ledger keeps), so nothing is lost to floating point.
const SCALE = 8;

function parseDec(text) {
  const match = /^(\d*)(?:\.(\d*))?$/.exec((text || "").replace(/[,\s]/g, ""));
  if (!match || (match[1] === "" && !match[2])) return null;
  const fraction = (match[2] || "").padEnd(SCALE, "0").slice(0, SCALE);
  return BigInt(match[1] || "0") * 10n ** BigInt(SCALE) + BigInt(fraction);
}

function formatDec(value) {
  const sign = value < 0n ? "-" : "";
  const abs = value < 0n ? -value : value;
  const whole = (abs / 10n ** BigInt(SCALE)).toString();
  let fraction = (abs % 10n ** BigInt(SCALE)).toString().padStart(SCALE, "0").replace(/0+$/, "");
  fraction = fraction.padEnd(2, "0");
  return `${sign}${whole}.${fraction}`;
}

function money(value) {
  const [whole, fraction] = formatDec(value).split(".");
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${fraction}`;
}

const txnState = { currencyChosen: false };

function rowAccount(row) {
  return row.querySelector('select[name="account"]');
}

function rowCommodity(row) {
  const option = rowAccount(row).selectedOptions[0];
  return option ? option.dataset.commodity || "" : "";
}

function txnCurrency(form) {
  const select = form.querySelector('select[name="currency"]');
  return select ? select.value : form.dataset.currency;
}

// A row holding something other than the transaction's currency says what it is worth in it.
function isForeign(row, currency) {
  const worth = row.querySelector('[name="value"]');
  const held = rowCommodity(row);
  return !!worth && held !== "" && held !== currency;
}

// The field that carries a row's share of the total: the amount, or the worth for a foreign row.
function carrier(row, currency) {
  return isForeign(row, currency) ? row.querySelector('[name="value"]') : row.querySelector('[name="amount"]');
}

function rowShare(row, currency) {
  return parseDec(carrier(row, currency).value) || 0n;
}

function newRow(form, side) {
  const template = form.querySelector("#txn-row-template");
  const row = template.content.firstElementChild.cloneNode(true);
  row.querySelector('[name="side"]').value = side;
  // Copy the live account list: it may have gained accounts since the page loaded.
  const live = form.querySelector("[data-rows] select[data-account-select]");
  const select = rowAccount(row);
  if (live) select.innerHTML = live.innerHTML;
  select.value = "";
  return row;
}

function setSuggestion(row, currency, text) {
  const field = carrier(row, currency);
  if (document.activeElement === field) return; // never overwrite what is being typed
  field.value = text;
  field.classList.toggle("suggested", text !== "");
}

function recomputeTxn(form) {
  const total = parseDec(form.querySelector("#total").value) || 0n;
  const select = form.querySelector('select[name="currency"]');
  if (select && !txnState.currencyChosen) {
    // Follow the accounts: the default currency when it is involved, else what they all hold.
    const held = [...form.querySelectorAll("[data-row]")].map(rowCommodity).filter(Boolean);
    const options = [...select.options].map((o) => o.value);
    const wanted = held.includes(form.dataset.currency) ? form.dataset.currency
      : held.length && held.every((h) => h === held[0]) && options.includes(held[0]) ? held[0] : null;
    if (wanted) select.value = wanted;
  }
  const currency = txnCurrency(form);
  form.querySelectorAll("[data-row]").forEach((row) => {
    const foreign = isForeign(row, currency);
    const worth = row.querySelector('[name="value"]');
    if (worth) {
      worth.hidden = !foreign;
      worth.placeholder = `Worth in ${currency}`;
      if (!foreign) { worth.value = ""; worth.classList.remove("suggested"); }
    }
    row.querySelector('[name="amount"]').placeholder = foreign && rowCommodity(row) ? rowCommodity(row) : "0.00";
    // A row whose account changed hands the share to the other field: a leftover suggestion there goes.
    const idle = foreign ? row.querySelector('[name="amount"]') : worth;
    if (idle && idle.classList.contains("suggested")) {
      idle.value = "";
      idle.classList.remove("suggested");
    }
  });

  ["credit", "debit"].forEach((side) => {
    const list = form.querySelector(`[data-rows="${side}"]`);
    let rows = [...list.querySelectorAll("[data-row]")];
    let touched = rows.filter((r) => r.hasAttribute("data-touched"));
    let sum = touched.reduce((acc, r) => acc + rowShare(r, currency), 0n);
    const remaining = total - sum;

    // At most one untouched row, and only while something is left to allocate (or as the one row).
    let open = rows.filter((r) => !r.hasAttribute("data-touched"));
    if (remaining > 0n && open.length === 0) {
      const row = newRow(form, side);
      list.appendChild(row);
      open = [row];
    }
    open.slice(1).forEach((row) => {
      if (!rowAccount(row).value && !row.contains(document.activeElement)) row.remove();
    });
    rows = [...list.querySelectorAll("[data-row]")];
    open = rows.filter((r) => !r.hasAttribute("data-touched"));
    if (remaining <= 0n && rows.length > 1) {
      open.forEach((row) => {
        if (!rowAccount(row).value && !row.contains(document.activeElement)) row.remove();
      });
      rows = [...list.querySelectorAll("[data-row]")];
      open = rows.filter((r) => !r.hasAttribute("data-touched"));
    }
    open.forEach((row, index) => setSuggestion(row, currency, index === 0 && remaining > 0n ? formatDec(remaining) : ""));
    rows.forEach((row) => {
      const only = rows.length === 1;
      row.querySelector("[data-remove-row]").hidden = only && !rowAccount(row).value && !row.hasAttribute("data-touched");
    });

    const status = form.querySelector(`[data-status="${side}"]`);
    const allocated = rows.reduce((acc, r) => acc + rowShare(r, currency), 0n);
    const left = total - allocated;
    status.classList.toggle("ok", total > 0n && left === 0n);
    status.classList.toggle("off", left !== 0n && total > 0n && rows.some((r) => rowShare(r, currency) > 0n));
    status.textContent =
      total === 0n ? ""
      : left === 0n ? `${money(total)} ${currency} allocated`
      : left > 0n ? `${money(left)} ${currency} left to allocate`
      : `${money(-left)} ${currency} over`;
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("form[data-txn-form]");
  if (!form) return;
  txnState.currencyChosen = form.hasAttribute("data-editing"); // an existing transaction keeps its currency
  recomputeTxn(form);
});

document.body.addEventListener("input", (event) => {
  const form = event.target.closest && event.target.closest("form[data-txn-form]");
  if (!form) return;
  const row = event.target.closest("[data-row]");
  if (row) {
    const currency = txnCurrency(form);
    if (event.target === carrier(row, currency)) {
      event.target.classList.remove("suggested");
      if (event.target.value.trim() === "") row.removeAttribute("data-touched");
      else row.setAttribute("data-touched", "");
    }
  }
  recomputeTxn(form);
});

document.body.addEventListener("change", (event) => {
  const form = event.target.closest && event.target.closest("form[data-txn-form]");
  if (!form) return;
  if (event.target.matches('select[name="currency"]')) txnState.currencyChosen = true;
  recomputeTxn(form);
});

// Leaving a field lets the suggestion settle (it is never rewritten while typing).
document.body.addEventListener("focusout", (event) => {
  const form = event.target.closest && event.target.closest("form[data-txn-form]");
  if (form) setTimeout(() => recomputeTxn(form), 0);
});

// A suggested amount is selected on entry, so typing replaces it.
document.body.addEventListener("focusin", (event) => {
  if (event.target.matches && event.target.matches("input.suggested")) event.target.select();
});

document.body.addEventListener("click", (event) => {
  const form = event.target.closest && event.target.closest("form[data-txn-form]");
  if (!form) return;
  const remove = event.target.closest("[data-remove-row]");
  if (remove) {
    const row = remove.closest("[data-row]");
    const list = row.parentElement;
    if (list.querySelectorAll("[data-row]").length > 1) row.remove();
    else {
      rowAccount(row).value = "";
      row.querySelectorAll('[name="amount"], [name="value"]').forEach((f) => { f.value = ""; });
      row.removeAttribute("data-touched");
    }
    recomputeTxn(form);
    return;
  }
  if (event.target.closest("[data-swap-sides]")) {
    const from = form.querySelector('[data-rows="credit"]');
    const to = form.querySelector('[data-rows="debit"]');
    const fromRows = [...from.children];
    const toRows = [...to.children];
    fromRows.forEach((row) => { row.querySelector('[name="side"]').value = "debit"; to.appendChild(row); });
    toRows.forEach((row) => { row.querySelector('[name="side"]').value = "credit"; from.appendChild(row); });
    recomputeTxn(form);
  }
});
