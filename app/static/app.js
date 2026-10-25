// ---- Amount fields only take what makes an amount ----
// Digits, commas to group them, one decimal point and (first only) a minus sign: "42.00.00" or "12a" cannot be typed or
// pasted, nor more decimals than the currency keeps (<html data-places>: two for rupees). This runs before the other input handlers (capture), so what they read is already clean.
function cleanAmount(text) {
  const places = Number(document.documentElement.dataset.places ?? 2);
  let out = "";
  let dot = false;
  let fraction = 0;
  for (const ch of text) {
    if (ch >= "0" && ch <= "9") {
      if (dot && fraction >= places) continue;
      if (dot) fraction += 1;
      out += ch;
    }
    else if (ch === ",") out += ch;
    else if (ch === "." && !dot && places > 0) { dot = true; out += ch; }
    else if (ch === "-" && out === "") out += ch;
  }
  return out.replace(/^(-?)0+(?=\d)/, "$1"); // no zeros in front: "01" is 1, "00.5" is 0.5
}

// When the person leaves an amount (or sends the form) it is written out whole: no commas or zeros in front, and the
// decimals the currency keeps ("1." and "1.1" become 1.00 and 1.10 for rupees). Anything that is not a number stays as typed.
function tidyAmount(text) {
  const places = Number(document.documentElement.dataset.places ?? 2);
  let t = text.replace(/[,\s]/g, "");
  const sign = t.startsWith("-") ? "-" : "";
  t = t.replace("-", "");
  if (t === "" || t === "." || !/^\d*\.?\d*$/.test(t)) return text;
  const [whole, fraction = ""] = t.split(".");
  const digits = whole.replace(/^0+(?=\d)/, "") || "0";
  return sign + digits + (places ? "." + fraction.slice(0, places).padEnd(places, "0") : "");
}

// The amount of a transaction is grouped as it is typed (12,34,567.00 for rupees): `groupAmount` puts the commas in
// whatever number it is given and leaves anything else alone. Fields that carry `data-group` use it.
function groupAmount(text) {
  const match = /^(-?)(\d*)(\.\d*)?$/.exec(text.replace(/,/g, ""));
  return match ? match[1] + groupDigits(match[2]) + (match[3] || "") : text;
}

function tidyField(field) {
  const tidy = field.hasAttribute("data-group") ? groupAmount(tidyAmount(field.value)) : tidyAmount(field.value);
  if (tidy === field.value) return false;
  field.value = tidy;
  return true;
}

const isAmountField = (el) => el && el.tagName === "INPUT" && el.getAttribute("inputmode") === "decimal";
document.addEventListener("focusout", (event) => {
  if (isAmountField(event.target) && tidyField(event.target)) event.target.dispatchEvent(new Event("input", { bubbles: true }));
}, true);
document.addEventListener("submit", (event) => {
  if (event.target.querySelectorAll) event.target.querySelectorAll('input[inputmode="decimal"]').forEach(tidyField);
}, true);

document.addEventListener("input", (event) => {
  const field = event.target;
  if (!field || field.tagName !== "INPUT" || field.getAttribute("inputmode") !== "decimal") return;
  const clean = cleanAmount(field.value);
  const cleaned = field.hasAttribute("data-group") ? groupAmount(clean) : clean;
  if (cleaned === field.value) return;
  // Keep the cursor after the same digits as before (commas come and go as the number is grouped).
  const caret = field.selectionStart ?? field.value.length;
  const digits = cleanAmount(field.value.slice(0, caret)).replace(/,/g, "").length;
  field.value = cleaned;
  let seen = 0;
  let at = cleaned.length;
  for (let i = 0; i < cleaned.length; i++) {
    if (seen >= digits) { at = i; break; }
    if (cleaned[i] !== ",") seen += 1;
  }
  try { field.setSelectionRange(at, at); } catch (e) { /* not every input type allows it */ }
}, true);

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
  const side = row ? row.querySelector('[name="side"]').value : "credit";
  const form = select.closest("form[data-txn-form]");
  const roots = form && KINDS[form.dataset.txnKind] ? KINDS[form.dataset.txnKind][side].roots : null;
  if (roots) return roots[0];
  return side === "debit" ? "Expenses" : "Assets";
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
  const txnForm = document.querySelector("form[data-txn-form]");
  if (txnForm) {
    // The kind's filter applies to the fresh list too; a new account the kind doesn't offer switches to "Other".
    txnForm._all = withoutSelection(options);
    const target = quickTarget;
    applyKind(txnForm, txnForm.dataset.txnKind);
    if (target && target.value !== aid) {
      target.value = aid;
      if (target.value !== aid) {
        applyKind(txnForm, "other");
        target.value = aid;
      }
    }
    if (target) target.dataset.previous = target.value;
  }
  document.querySelectorAll("select[data-account-select]").forEach((select) => {
    if (txnForm && txnForm.contains(select)) return;
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

// Open the profile section named in the URL (#currency, #appearance ...).
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

function groupDigits(whole) {
  // Lakhs and crores for rupees (12,34,567), thousands otherwise (1,234,567); the page says which on <html>.
  if (document.documentElement.dataset.grouping === "indian") {
    return whole.replace(/\B(?=(\d{2})*\d{3}(?!\d))/g, ",");
  }
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

function money(value) {
  const [whole, fraction] = formatDec(value).split(".");
  return `${groupDigits(whole)}.${fraction}`;
}

// What each kind of entry offers on each side. iOS ignores hidden options, so the lists are rebuilt, not hidden.
const KINDS = {
  expense: {
    credit: { roots: ["Assets", "Liabilities"], hint: "the account you paid with" },
    debit: { roots: ["Expenses"], hint: "what it was for" },
  },
  income: {
    credit: { roots: ["Income"], hint: "who paid you" },
    debit: { roots: ["Assets", "Liabilities"], hint: "where it landed" },
  },
  transfer: {
    credit: { roots: ["Assets", "Liabilities"], hint: "the account the money leaves" },
    debit: { roots: ["Assets", "Liabilities"], hint: "the account it goes to" },
  },
  other: {
    credit: { roots: null, hint: "where the money comes from" },
    debit: { roots: null, hint: "where the money goes" },
  },
};

function withoutSelection(html) {
  const holder = document.createElement("select");
  holder.innerHTML = html;
  holder.querySelectorAll("option[selected]").forEach((option) => option.removeAttribute("selected"));
  return holder.innerHTML;
}

// The account list for one side of a kind: the placeholder entries and the groups whose type it offers.
function optionsFor(all, roots) {
  if (!roots) return all;
  const holder = document.createElement("select");
  holder.innerHTML = all;
  holder.querySelectorAll("optgroup").forEach((group) => {
    if (!roots.includes(group.label)) group.remove();
  });
  return holder.innerHTML;
}

function applyKind(form, kind) {
  if (!KINDS[kind]) kind = "other";
  form.dataset.txnKind = kind;
  form.querySelector("[data-kind-input]").value = kind;
  form.querySelectorAll("[data-kind]").forEach((button) => {
    button.setAttribute("aria-pressed", button.dataset.kind === kind ? "true" : "false");
  });
  form.querySelectorAll("[data-row]").forEach((row) => {
    const select = rowAccount(row);
    const side = row.querySelector('[name="side"]').value;
    const current = select.value;
    select.innerHTML = optionsFor(form._all, KINDS[kind][side].roots);
    select.value = current; // stays when the kind still offers it, else the empty choice
    if (select.value !== current) select.value = "";
    select.dataset.previous = select.value;
  });
  ["credit", "debit"].forEach((side) => {
    const hint = form.querySelector(`[data-side-section="${side}"] [data-side-hint]`);
    if (hint) hint.textContent = KINDS[kind][side].hint;
  });
  recomputeTxn(form);
}

// A sheet opens at once with grey placeholders in the shape of its content, which the real thing replaces when it arrives;
// if it never does (an error, no connection) the sheet closes again.
const SHEET_BODIES = ["txn-sheet-body", "cat-sheet-body", "related-picker-body"];
const SHEET_SKELETON = '<div class="skeleton" aria-hidden="true"><i class="sk sk-title"></i><i class="sk sk-figure"></i><i class="sk sk-row"></i><i class="sk sk-row"></i><i class="sk sk-row"></i></div>';
document.body.addEventListener("htmx:beforeRequest", (event) => {
  const body = event.detail && event.detail.target;
  if (!body || !SHEET_BODIES.includes(body.id)) return;
  const dialog = document.getElementById(body.id.replace("-body", ""));
  if (!dialog) return;
  body.innerHTML = SHEET_SKELETON;
  dialog.dataset.loading = "1";
  loadingBy.set(dialog, event.detail.elt);
  if (!dialog.open) dialog.showModal();
});
// A sheet closed while its content is still on the way stays closed: the request is dropped, so nothing arrives to reopen it.
const loadingBy = new WeakMap();
document.addEventListener("close", (event) => {
  const dialog = event.target;
  if (!dialog || !dialog.dataset || !dialog.dataset.loading) return;
  delete dialog.dataset.loading;
  const from = loadingBy.get(dialog);
  loadingBy.delete(dialog);
  if (from && window.htmx) window.htmx.trigger(from, "htmx:abort");
  const body = dialog.querySelector(".sheet-body");
  if (body && body.querySelector(".skeleton")) body.innerHTML = "";
}, true);
["htmx:responseError", "htmx:sendError", "htmx:timeout"].forEach((name) => {
  document.body.addEventListener(name, (event) => {
    const body = event.detail && event.detail.target;
    if (!body || !SHEET_BODIES.includes(body.id) || !body.querySelector(".skeleton")) return;
    body.innerHTML = "";
    const dialog = document.getElementById(body.id.replace("-body", ""));
    if (dialog && dialog.open) dialog.close();
  });
});

// The details sheet over a list: it opens when its content arrives and closes on a tap outside it.
document.body.addEventListener("htmx:afterSwap", (event) => {
  const id = event.target && event.target.id;
  if (!SHEET_BODIES.includes(id)) return;
  const dialog = document.getElementById(id.replace("-body", ""));
  if (dialog) { delete dialog.dataset.loading; loadingBy.delete(dialog); }
  if (dialog && !dialog.open) dialog.showModal();
  const first = dialog && dialog.querySelector("[data-autofocus]");
  if (first && window.matchMedia("(hover: hover) and (pointer: fine)").matches) first.focus();
});
// A tap that starts on a sheet's Save counts as Save even when the sheet moves under the finger before it ends (the keyboard
// opening or closing shifts it): the browser then sends the click to whatever is under the finger, which closed the sheet
// without saving and made Save feel like it needed several taps.
let pressedSave = null;
document.addEventListener("pointerdown", (event) => {
  pressedSave = event.target.closest ? event.target.closest('dialog.sheet button[type="submit"]') : null;
}, true);
document.addEventListener("click", (event) => {
  const button = pressedSave;
  pressedSave = null;
  if (!button || !button.isConnected || event.target === button || button.contains(event.target)) return;
  const dialog = button.closest("dialog");
  if (!dialog || !(dialog === event.target || dialog.contains(event.target))) return;
  event.preventDefault();
  event.stopPropagation();
  if (button.form) button.form.requestSubmit(button);
}, true);
// While a field in the sheet has the keyboard open, a tap on the dim area only puts the keyboard away; it never throws the
// sheet (and what was typed) away. The next tap outside closes it.
// (The browser moves focus off the field when the press starts, so what was focused is noted then.)
let wasTyping = false;
// A press that began on the sheet's own content never closes it, even when the sheet moves under the finger before the
// release (focusing the amount makes the sheet change shape) and the click lands on the dim area instead.
let pressedInside = false;
document.addEventListener("pointerdown", (event) => {
  pressedInside = event.target instanceof Element && !(event.target instanceof HTMLDialogElement) && !!event.target.closest("dialog.sheet-bottom");
  const field = document.activeElement;
  wasTyping = event.target instanceof HTMLDialogElement && !!field && event.target.contains(field) && field.matches("input, select, textarea");
}, true);
document.body.addEventListener("click", (event) => {
  const dialog = event.target;
  if (!(dialog instanceof HTMLDialogElement) || !dialog.classList.contains("sheet-bottom")) return;
  if (pressedInside) {
    pressedInside = false;
    return;
  }
  if (wasTyping) {
    wasTyping = false;
    if (document.activeElement && dialog.contains(document.activeElement)) document.activeElement.blur();
    return;
  }
  dialog.close();
});

// ---- Sheets and the soft keyboard ----
// A bottom sheet sits under the keyboard on a phone, so Save could not be reached until the keyboard was put away. The
// visual viewport tells how much of the screen the keyboard takes (--kb) and how tall the visible part is (--vvh): the
// sheet is lifted above the keyboard, and while a field is being typed in it shows only what is needed (`typing`), so it
// fits even on a small phone.
(() => {
  const vv = window.visualViewport;
  const place = () => {
    if (!vv) return;
    const root = document.documentElement.style;
    // With no field focused there is no keyboard, whatever the viewport says: iOS Safari's keyboard-down button (the tick)
    // puts the keyboard away without a resize event, which left the sheet lifted over empty space and Save untappable.
    const field = document.activeElement;
    const typing = !!field && field.matches && field.matches("input, select, textarea") && !!field.closest("dialog.sheet");
    root.setProperty("--kb", `${typing ? Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop)) : 0}px`);
    root.setProperty("--vvh", `${Math.round(vv.height)}px`);
  };
  if (vv) {
    vv.addEventListener("resize", place);
    vv.addEventListener("scroll", place);
    place();
  }
  const sheetOf = (event) => (event.target.closest && event.target.matches && event.target.matches("input, select, textarea") ? event.target.closest("dialog.sheet") : null);
  document.addEventListener("focusin", (event) => {
    const dialog = sheetOf(event);
    if (!dialog) return;
    clearTimeout(dialog._typingTimer);
    dialog.classList.add("typing");
    place();
  });
  document.addEventListener("focusout", (event) => {
    const dialog = sheetOf(event);
    // Later than the tap on Save that caused it, so the sheet does not change shape under the finger.
    if (!dialog) return;
    dialog._typingTimer = setTimeout(() => dialog.classList.remove("typing"), 300);
    // The keyboard is going: lower the sheet now, and look again as the viewport settles (iOS may send no event at all).
    place();
    [100, 350, 700].forEach((ms) => setTimeout(() => {
      place();
      if (vv && vv.offsetTop && !document.activeElement.matches("input, select, textarea")) window.scrollTo(0, 0);
    }, ms));
  });
})();

// A suggestion chip fills the payee and the accounts used the last time (the first row of each side).
function applySuggestion(form, chip, focus = true) {
  const payee = form.querySelector("#payee");
  if (payee && focus) payee.value = chip.dataset.payee; // never rewrite what is being typed
  applyKind(form, chip.dataset.suggestKind);
  [["credit", chip.dataset.from], ["debit", chip.dataset.to]].forEach(([side, id]) => {
    const select = form.querySelector(`[data-rows="${side}"] select[name="account"]`);
    if (!select) return;
    select.value = id;
    select.dataset.previous = select.value;
  });
  form.querySelectorAll("[data-suggest]").forEach((c) => c.setAttribute("aria-pressed", c === chip ? "true" : "false"));
  recomputeTxn(form);
  if (!focus) return;
  const total = form.querySelector("#total");
  (total && !total.value.trim() ? total : form.querySelector('button[type="submit"]')).focus();
}

// Typing a payee you know in full fills the accounts too, once, while nothing is chosen yet; focus stays where it is.
document.body.addEventListener("htmx:afterSwap", (event) => {
  if (!event.target || event.target.id !== "payee-chips") return;
  const form = event.target.closest("form[data-txn-form]");
  const exact = event.target.querySelector("[data-suggest][data-exact]");
  if (!form || !exact) return;
  const nothingChosen = ["credit", "debit"].every((side) => {
    const select = form.querySelector(`[data-rows="${side}"] select[name="account"]`);
    return select && !select.value;
  });
  if (nothingChosen) applySuggestion(form, exact, false);
});

function rowAccount(row) {
  return row.querySelector('select[name="account"]');
}

function newRow(form, side) {
  const template = form.querySelector("#txn-row-template");
  const row = template.content.firstElementChild.cloneNode(true);
  row.querySelector('[name="side"]').value = side;
  // Copy the live account list: it may have gained accounts since the page loaded.
  const select = rowAccount(row);
  select.innerHTML = optionsFor(form._all, (KINDS[form.dataset.txnKind] || KINDS.other)[side].roots);
  select.value = "";
  return row;
}

function rowShare(row) {
  return parseDec(row.querySelector('[name="amount"]').value) || 0n;
}

function setSuggestion(row, text) {
  const field = row.querySelector('[name="amount"]');
  if (document.activeElement === field) return; // never overwrite what is being typed
  field.value = groupAmount(text);
  field.classList.toggle("suggested", text !== "");
}

function recomputeTxn(form) {
  const field = form.querySelector("#total");
  field.style.setProperty("--n", Math.max(field.value.length - 0.55 * (field.value.split(",").length - 1), 4)); // the amount is as wide as what is typed, so the rupee sign sits against the digits
  const total = parseDec(field.value) || 0n;
  const currency = form.dataset.currency;

  ["credit", "debit"].forEach((side) => {
    const list = form.querySelector(`[data-rows="${side}"]`);
    let rows = [...list.querySelectorAll("[data-row]")];
    let touched = rows.filter((r) => r.hasAttribute("data-touched"));
    let sum = touched.reduce((acc, r) => acc + rowShare(r), 0n);
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
    open.forEach((row, index) => setSuggestion(row, index === 0 && remaining > 0n ? formatDec(remaining) : ""));
    rows.forEach((row) => {
      const only = rows.length === 1;
      row.querySelector("[data-remove-row]").hidden = only; // one row has nothing to remove
    });

    const status = form.querySelector(`[data-status="${side}"]`);
    const allocated = rows.reduce((acc, r) => acc + rowShare(r), 0n);
    const left = total - allocated;
    status.classList.toggle("ok", total > 0n && left === 0n);
    status.classList.toggle("off", left !== 0n && total > 0n && rows.some((r) => rowShare(r) > 0n));
    status.textContent =
      total === 0n ? ""
      : left === 0n ? "" // balanced is the normal state, so nothing is said about it
      : left > 0n ? `${money(left)} ${currency} left to allocate`
      : `${money(-left)} ${currency} over`;
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("form[data-txn-form]");
  if (!form) return;
  const first = form.querySelector("select[data-account-select]");
  form._all = first ? withoutSelection(first.innerHTML) : "";
  form.querySelectorAll("[data-group]").forEach((field) => { if (field.value) tidyField(field); });
  form.querySelectorAll("[data-rows]").forEach((list) => {
    const rows = list.querySelectorAll("[data-row]");
    rows.forEach((row) => { row.querySelector("[data-remove-row]").hidden = rows.length === 1; });
  });
  applyKind(form, form.querySelector("[data-kind-input]").value);
});

document.body.addEventListener("input", (event) => {
  const form = event.target.closest && event.target.closest("form[data-txn-form]");
  if (!form) return;
  const row = event.target.closest("[data-row]");
  if (row) {
    if (event.target === row.querySelector('[name="amount"]')) {
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
  recomputeTxn(form);
});

// Leaving a field lets the suggestion settle (it is never rewritten while typing).
document.body.addEventListener("focusout", (event) => {
  const form = event.target.closest && event.target.closest("form[data-txn-form]");
  if (form) setTimeout(() => recomputeTxn(form), 0);
});

// A suggested amount is selected on entry, so typing replaces it.
// Safari puts the caret back when the click or tap ends, so the selection is made after that too.
document.body.addEventListener("focusin", (event) => {
  const field = event.target;
  if (!(field.matches && field.matches("input.suggested"))) return;
  field.select();
  field.dataset.fresh = "1";
  setTimeout(() => {
    if (field.classList.contains("suggested")) field.select();
  }, 0);
});
document.body.addEventListener("mouseup", (event) => {
  const field = event.target;
  if (field.dataset && field.dataset.fresh) {
    delete field.dataset.fresh;
    if (field.classList.contains("suggested")) event.preventDefault();
  }
});
document.body.addEventListener("touchend", (event) => {
  const field = event.target;
  if (field.dataset && field.dataset.fresh && field.classList.contains("suggested")) {
    delete field.dataset.fresh;
    event.preventDefault();
  }
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
      row.querySelectorAll('[name="amount"]').forEach((f) => { f.value = ""; });
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
    // An expense turned round is no longer an expense (a refund, say): every account is offered again.
    applyKind(form, form.dataset.txnKind === "transfer" ? "transfer" : "other");
    return;
  }
  const chip = event.target.closest("[data-suggest]");
  if (chip) {
    applySuggestion(form, chip);
    return;
  }
  const kindButton = event.target.closest("[data-kind]");
  if (kindButton) {
    // Tapping the selected kind again selects nothing: every account is offered ("other").
    const selected = kindButton.getAttribute("aria-pressed") === "true";
    applyKind(form, selected ? "other" : kindButton.dataset.kind);
  }
});

// Account form: a payment category goes only with an account that is not part of the budget. A new account asks only under
// Assets and Liabilities (the options carry their root in `data-root`): an asset starts in the budget, a card or loan outside
// it. Hidden fields are disabled so they are not sent.
(function budgetChoice() {
  const sync = (fields) => {
    const box = fields.querySelector('input[name="on_budget"]');
    const payment = fields.querySelector("[data-payment-category]");
    if (!box) return;
    const out = !box.checked;
    const now = fields.querySelector("[data-budget-summary]");
    if (now) {
      const choice = payment && payment.querySelector("select");
      now.textContent = !out ? "Part of the budget"
        : choice && choice.value ? "Outside the budget · payments are spending"
        : "Outside the budget";
    }
    if (payment) payment.hidden = !out;
  };
  const apply = (select) => {
    const fields = select.form && select.form.querySelector("[data-budget-fields]");
    if (!fields || !select.options.length || !select.selectedOptions[0] || !("root" in select.selectedOptions[0].dataset)) return;
    const root = select.selectedOptions[0].dataset.root;
    const asked = root === "Assets" || root === "Liabilities";
    fields.hidden = !asked;
    fields.dataset.root = root;
    fields.querySelectorAll("input, select").forEach((el) => { el.disabled = !asked; });
    if (!asked) return;
    const box = fields.querySelector('input[name="on_budget"]');
    box.checked = root === "Assets";
    // Under a built-in group (Bank Accounts, Investments, Loans...) the account starts as that group says.
    const start = select.selectedOptions[0].dataset.start;
    if (start) box.checked = start === "budget";
    sync(fields);
  };
  document.body.addEventListener("change", (event) => {
    if (!event.target.matches) return;
    if (event.target.matches('form select[name="parent_id"]')) apply(event.target);
    if (event.target.matches('input[name="on_budget"], select[name="payment_category"]')) {
      const fields = event.target.closest("[data-budget-fields]");
      if (fields) sync(fields);
    }
  });
  const first = document.querySelector('[data-budget-fields]');
  const form = first && first.closest("form");
  const select = form && form.querySelector('select[name="parent_id"]');
  if (select && select.value) {
    // The parent is already chosen (from a type's tab, an account's page or the edit page): the server drew the right state;
    // only disable what is hidden.
    first.querySelectorAll("input, select").forEach((el) => { el.disabled = first.hidden; });
  } else if (first) {
    first.querySelectorAll("input, select").forEach((el) => { el.disabled = true; });
  }
})();

// ---- Accounts page: closed accounts ----
(function accountsPage() {
  const page = document.querySelector("[data-accounts]");
  if (!page) return;

  // One button shows the closed accounts (they carry a badge) and goes away.
  const more = page.querySelector("[data-load-more-accounts]");
  if (more) {
    more.addEventListener("click", () => {
      page.classList.add("show-closed");
      more.closest(".unused-toggle").remove();
    });
  }
})();

// ---- Offline, failed requests and loading ----
// One banner says what is wrong (the entry on the page is never cleared: a failed save leaves the form as it was).
(() => {
  const banner = document.getElementById("net-banner");
  if (!banner) return;
  let timer = null;
  function show(text, kind) {
    banner.textContent = text;
    banner.dataset.kind = kind;
    banner.hidden = false;
    clearTimeout(timer);
    if (kind !== "offline") timer = setTimeout(hide, 10000);
  }
  function hide() {
    banner.hidden = true;
  }
  function sync() {
    if (navigator.onLine === false) show("You\u2019re offline. You can look around, but nothing can be saved until you\u2019re back.", "offline");
    else if (banner.dataset.kind === "offline") hide();
  }
  window.addEventListener("online", sync);
  window.addEventListener("offline", sync);
  sync();

  document.body.addEventListener("htmx:sendError", () => {
    if (navigator.onLine === false) return sync();
    show("Couldn\u2019t save just now. Your entry is still here. Check your connection and try again.", "error");
  });
  document.body.addEventListener("htmx:timeout", () => show("That took too long. Your entry is still here. Try again.", "error"));
  document.body.addEventListener("htmx:responseError", (event) => {
    if (event.detail.xhr.status >= 500) show("Something went wrong on our side. Your entry is still here. Try again in a moment.", "error");
  });
  document.body.addEventListener("htmx:afterRequest", (event) => {
    if (event.detail.successful && banner.dataset.kind === "error") hide();
  });

  // A thin bar at the top while a request or a page is loading.
  let pending = 0;
  const bar = (on) => document.body.classList.toggle("loading", on);
  document.body.addEventListener("htmx:beforeRequest", () => bar(++pending > 0));
  document.body.addEventListener("htmx:afterRequest", () => bar((pending = Math.max(0, pending - 1)) > 0));
  window.addEventListener("beforeunload", () => bar(true));
  window.addEventListener("pageshow", () => bar((pending = 0) > 0));
})();

// A new entry opens with the amount ready to type on a computer. On a phone nothing is focused: the grey 0.00 stays
// visible, and tapping the amount hides it, shows the cursor and opens the keyboard (a script cannot open the keyboard).
(() => {
  const first = document.querySelector("[data-autofocus]");
  if (first && window.matchMedia("(hover: hover) and (pointer: fine)").matches) first.focus();
})();

// ---- Budget: unused groups can be shown ----
// The "N things need you" line on the budget page opens and closes the list of what needs a decision.
(() => {
  document.body.addEventListener("click", (event) => {
    const badge = event.target.closest && event.target.closest("[data-toggle-attn]");
    if (!badge) return;
    const panel = document.getElementById(badge.getAttribute("aria-controls"));
    if (!panel) return;
    panel.hidden = !panel.hidden;
    badge.setAttribute("aria-expanded", String(!panel.hidden));
    const more = badge.querySelector(".need-more");
    if (more) more.textContent = panel.hidden ? "Show ▾" : "Hide ▴";
  });
})();

(() => {
  document.body.addEventListener("click", (event) => {
    const button = event.target.closest && event.target.closest("[data-toggle-budget-unused]");
    if (!button) return;
    const tree = document.getElementById("budget");
    const shown = tree.classList.toggle("show-budget-unused");
    const n = button.dataset.count;
    button.textContent = shown ? `Hide the ${n} unused` : `${n} unused group${n === "1" ? "" : "s"} hidden · Show`;
  });
})();

// ---- An account's "i" and its "..." menu share the same place: opening one closes the other ----
(() => {
  document.addEventListener("toggle", (event) => {
    const opened = event.target;
    if (!(opened instanceof HTMLDetailsElement) || !opened.open) return;
    if (!opened.matches("details.menu, details.note-info")) return;
    document.querySelectorAll("details.menu[open], details.note-info[open]").forEach((other) => {
      if (other !== opened) other.open = false;
    });
  }, true);
})();

// ---- A group's budget cannot be set below what its subcategories add up to: the field turns red and nothing is saved ----
(function groupMinimum() {
  const below = (input) => {
    const value = Number(input.value.replace(/,/g, "")) || 0;
    return value < Number(input.dataset.min);
  };
  document.addEventListener("input", (event) => {
    const input = event.target;
    if (input instanceof HTMLInputElement && input.dataset.min !== undefined) {
      input.setAttribute("aria-invalid", below(input) ? "true" : "false");
    }
  });
  document.addEventListener("submit", (event) => {
    const input = event.target.querySelector && event.target.querySelector("input[data-min]");
    if (input && below(input)) {
      event.preventDefault();
      event.stopImmediatePropagation();
      input.setAttribute("aria-invalid", "true");
    }
  }, true);
  document.addEventListener("htmx:responseError", (event) => {
    const input = event.target.querySelector && event.target.querySelector("input[data-min]");
    if (input) input.setAttribute("aria-invalid", "true");
  });
})();

// The month in a month pill is a native month picker (an invisible `input[type=month]` over its name): choosing a month
// opens that month's page. The page's address is in `data-url`, with {month} where the month goes. Where the browser has no
// month picker the field is a plain text box, so only a complete YYYY-MM is taken.
document.addEventListener("change", (event) => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || !input.classList.contains("month-input")) return;
  const value = input.value;
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(value) || value < input.min || value > input.max) return;
  window.location.href = input.dataset.url.replace("{month}", value);
});
document.addEventListener("click", (event) => {
  // Desktop browsers open their picker from the little icon only; a tap anywhere on the name opens it here.
  const input = event.target;
  if (input instanceof HTMLInputElement && input.classList.contains("month-input") && typeof input.showPicker === "function") {
    try { input.showPicker(); } catch (e) { /* not allowed here: the browser's own control remains */ }
  }
});

// Bars fill from zero once, when a page loads; after that (an amount assigned, a sheet saved) they are only replaced.
setTimeout(() => { document.documentElement.dataset.live = "1"; }, 900);

// After saving an entry the toast carries Undo for it; the saved entry's row, when the page lists it, settles in with a short tint.
(() => {
  const undo = document.querySelector('.toast [hx-post^="/transactions/"][hx-post$="/delete"]');
  const tid = undo && undo.getAttribute("hx-post").split("/")[2];
  if (!tid) return;
  document.querySelectorAll("a.tx").forEach((row) => {
    if ((row.getAttribute("href") || "").startsWith(`/transactions/${tid}/`)) row.classList.add("tx-new");
  });
})();

// ---- The Transactions filter sheet: three fields, each opens a searchable list ----
(() => {
  const dialog = document.getElementById("tx-filter");
  if (!dialog) return;
  const form = dialog.querySelector("[data-filter-form]");
  const main = form.querySelector("[data-filter-main]");
  const lists = form.querySelectorAll("[data-filter-list]");
  const show = (view) => {
    main.hidden = view !== main;
    lists.forEach((list) => { list.hidden = list !== view; });
  };
  document.querySelectorAll("[data-open-filter]").forEach((button) => button.addEventListener("click", () => { show(main); dialog.showModal(); }));
  form.addEventListener("click", (event) => {
    const pick = event.target.closest("[data-pick]");
    if (pick) {
      const list = form.querySelector(`[data-filter-list="${pick.dataset.pick}"]`);
      show(list);
      if (pick.dataset.pick === "tag" && window.htmx) {  // the tags are fetched the first time the list is opened
        const loader = list.querySelector("[hx-trigger]");
        if (loader) window.htmx.trigger(loader, "tags-open");
      }
      const search = list.querySelector("[data-filter-search]");
      search.value = "";
      list.querySelectorAll("li").forEach((li) => { li.hidden = false; });
      if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) search.focus();
      return;
    }
    if (event.target.closest("[data-filter-back]")) { show(main); return; }
    const option = event.target.closest("[data-filter-list] [data-value]");
    if (!option) return;
    const key = option.closest("[data-filter-list]").dataset.filterList;
    form.querySelector(`[data-filter-value="${key}"]`).value = option.dataset.value;
    const label = form.querySelector(`[data-filter-label="${key}"]`);
    label.textContent = option.dataset.label || label.dataset.any;
    label.classList.toggle("set", !!option.dataset.value);
    show(main);
  });
  form.addEventListener("input", (event) => {
    if (!event.target.matches("[data-filter-search]")) return;
    const text = event.target.value.trim().toLowerCase();
    event.target.closest("[data-filter-list]").querySelectorAll("li").forEach((li) => {
      li.hidden = !!text && !li.textContent.toLowerCase().includes(text);
    });
  });
  form.addEventListener("submit", () => {
    form.querySelectorAll("[data-filter-value]").forEach((input) => { if (!input.value) input.disabled = true; });
  });
})();

// ---- Tags on the Add screen: after a # in the note, the tags already in use are offered (what is typed narrows them) ----
(() => {
  let names = null;
  let loading = null;
  const load = () => {
    if (names) return Promise.resolve(names);
    loading ||= fetch("/transactions/tag-names", { headers: { Accept: "application/json" } })
      .then((response) => (response.ok ? response.json() : []))
      .catch(() => [])
      .then((list) => (names = list));
    return loading;
  };
  // The #word being typed at the caret: where it starts and the letters after the #.
  const wordAt = (input) => {
    const upto = input.value.slice(0, input.selectionStart ?? input.value.length);
    const found = /(^|\s)#([A-Za-z0-9_-]*)$/.exec(upto);
    return found ? { start: upto.length - found[2].length - 1, end: upto.length, text: found[2].toLowerCase() } : null;
  };
  const close = (pop) => { pop.hidden = true; pop.replaceChildren(); };
  document.addEventListener("input", async (event) => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement) || !input.matches("[data-tag-note]")) return;
    const pop = input.parentElement.querySelector(".tag-pop");
    if (!wordAt(input)) { close(pop); return; }
    const list = await load();
    const word = wordAt(input);
    if (!word) { close(pop); return; }
    const shown = list.filter((tag) => tag.tag.startsWith(word.text) && tag.tag !== word.text).slice(0, 5);
    pop.replaceChildren(...shown.map((tag) => {
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("role", "option");
      button.dataset.tag = tag.tag;
      button.append(`#${tag.tag}`);
      const uses = document.createElement("small");
      uses.className = "muted";
      uses.textContent = String(tag.uses);
      button.append(uses);
      return button;
    }));
    pop.hidden = !shown.length;
  });
  // Finish the word with the chosen tag.
  const choose = (button) => {
    const pop = button.closest(".tag-pop");
    const input = pop.parentElement.querySelector("[data-tag-note]");
    const word = wordAt(input);
    if (word) {
      input.value = `${input.value.slice(0, word.start)}#${button.dataset.tag} ${input.value.slice(word.end)}`;
      const caret = word.start + button.dataset.tag.length + 2;
      input.setSelectionRange(caret, caret);
    }
    close(pop);
    input.focus();
  };
  // A suggestion is chosen the moment the finger or the pointer goes down on it. Waiting for the click is too late on a
  // phone: the tap has taken the focus from the note by then, the field's focusout has closed the list and the click
  // finds nothing. Cancelling the press also keeps the focus (and the keyboard) on the note.
  let pressed = false;
  document.addEventListener("pointerdown", (event) => {
    const button = event.target instanceof Element && event.target.closest(".tag-pop [data-tag]");
    if (!button) return;
    event.preventDefault();
    choose(button);
    pressed = true;
  });
  // The list has closed by the time the press ends, so the click that finishes it would land on whatever lies under the
  // finger (the "Related transaction" row, say) and press that. That one click is swallowed.
  const release = () => { if (pressed) setTimeout(() => { pressed = false; }, 400); };
  document.addEventListener("pointerup", release);
  document.addEventListener("pointercancel", release);
  document.addEventListener("click", (event) => {
    if (pressed) {
      pressed = false;
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    // The same from the keyboard (Enter or Space on a focused suggestion arrives as a click).
    const button = event.target instanceof Element && event.target.closest(".tag-pop [data-tag]");
    if (button) choose(button);
  }, true);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !(event.target instanceof HTMLInputElement) || !event.target.matches("[data-tag-note]")) return;
    const pop = event.target.parentElement.querySelector(".tag-pop");
    if (pop && !pop.hidden) { close(pop); event.stopPropagation(); }
  });
  document.addEventListener("focusout", (event) => {
    if (event.target instanceof HTMLInputElement && event.target.matches("[data-tag-note]")) {
      const pop = event.target.parentElement.querySelector(".tag-pop");
      if (pop) close(pop);
    }
  });
})();

// ---- Relating an entry to an earlier one: the chip, the dashed row and the picker sheet ----
(() => {
  const set = (box, tid, label) => {
    box.querySelector("[data-related-value]").value = tid;
    box.querySelector("[data-related-label]").textContent = label;
    box.querySelector("[data-related-chip]").hidden = !tid;
    box.querySelector("[data-related-add]").hidden = !!tid;
  };
  document.addEventListener("click", (event) => {
    const pick = event.target.closest("[data-related-pick]");
    if (pick) {
      const box = document.querySelector("[data-related]");
      if (box) set(box, pick.dataset.relatedPick, pick.dataset.label);
      const dialog = pick.closest("dialog");
      if (dialog) dialog.close();
      return;
    }
    const clear = event.target.closest("[data-related-clear]");
    if (clear) set(clear.closest("[data-related]"), "", "");
  });
})();

// The payee suggestions are one row, on any width: chips that would wrap to a second row are left out (and come back when
// the row has room, as the window changes size or the person types and the list is replaced).
function fitPayeeChips() {
  const box = document.getElementById("payee-chips");
  if (!box) return;
  const chips = [...box.querySelectorAll(".chip")];
  chips.forEach((chip) => chip.classList.remove("fit-hidden"));
  if (!chips.length) return;
  const top = chips[0].offsetTop;
  chips.forEach((chip) => { if (chip.offsetTop > top) chip.classList.add("fit-hidden"); });
}
document.body.addEventListener("htmx:afterSwap", (event) => { if (event.target && event.target.id === "payee-chips") fitPayeeChips(); });
window.addEventListener("resize", fitPayeeChips);

// The date chip on the Add screen: a native date picker under the day's name ("Today, 24 Oct"); choosing a day renames it.
document.addEventListener("change", (event) => {
  const input = event.target;
  const chip = input instanceof HTMLInputElement && input.closest("[data-date-chip]");
  if (!chip || !input.value) return;
  const [y, m, d] = input.value.split("-").map(Number);
  const day = new Date(Date.UTC(y, m - 1, d));
  const today = chip.dataset.today;
  const part = (options) => day.toLocaleDateString("en-GB", { timeZone: "UTC", ...options });
  chip.querySelector("[data-date-label]").textContent =
    input.value === today ? `Today, ${d} ${part({ month: "short" })}`
    : input.value.slice(0, 4) === today.slice(0, 4) ? `${part({ weekday: "short" })}, ${d} ${part({ month: "short" })}`
    : `${d} ${part({ month: "short", year: "numeric" })}`;
});
document.addEventListener("click", (event) => {
  const input = event.target;
  if (input instanceof HTMLInputElement && input.closest("[data-date-chip]") && typeof input.showPicker === "function") {
    try { input.showPicker(); } catch (e) { /* not allowed here: the browser's own control remains */ }
  }
});
