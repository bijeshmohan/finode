# The design system

finode looks the way it does on purpose: **calm, minimal and quick to enter**. This page describes the look, the small set of parts every page is built from, the motion, and the rules that keep new pages consistent. The CSS is one file, `app/static/style.css`; the behaviour is `app/static/app.js`. [The web UI](web-ui.md) covers how pages are rendered and updated.

## Principles

1. **Phones first.** Every page is one column that works on a phone; from 60rem up a fixed sidebar replaces the top bar and tab bar and the column is centred in the space beside it. Nothing floats over the page.
2. **Fewer boxes.** Removing something or adding whitespace is preferred to adding a border, badge or card. A box earns its place only when it groups things that need telling apart.
3. **Colour means money.** Green and red appear only for money coming in or going out (and for an overspent category or an error). Actions are ink-coloured (near black in light, near white in dark). Blue marks what was added automatically (an assistant or a recurring rule).
4. **One of each part.** There is one switcher, one row, one tile, one sheet, one empty state. New pages reuse them; they do not draw their own.
5. **Calm motion.** Short, quiet transitions that explain a change (a chip gliding, a sheet rising). All of it switches off under `prefers-reduced-motion`.
6. **Nothing is lost on a failed save.** Forms are never cleared on an error, and the page says the entry is still there.

## Tokens

The tokens are CSS variables at the top of `style.css`. Style with tokens only, never literal colours (the white switch knob is the one exception).

| Group | Tokens |
|---|---|
| Surfaces and text | `--bg`, `--surface`, `--surface-2`, `--text`, `--muted`, `--faint` |
| Lines | `--border`, `--field-border` (stronger in dark so empty fields show), `--tile-border` |
| Action | `--accent`, `--accent-hover`, `--accent-soft`, `--on-accent` |
| Meaning | `--positive`, `--negative`, `--danger`, `--danger-soft`, `--warn`, `--warn-soft`, `--auto` |
| Shape and size | `--radius` (16px), `--radius-sm` (12px), `--tap` (44px), `--topbar-h`, `--tabbar-h`, `--sidebar-w`, `--bar-h` (3px, every progress bar) |

**Dark mode.** There are three blocks: the light tokens on `:root`, an automatic `prefers-color-scheme: dark` block, and a manual `[data-theme="dark"]` block. The two dark blocks must define the same tokens (a test compares them). The choice is per browser, in the `finode_theme` cookie that `base.html` reads. `favicon.svg` switches between ink and paper; `apple-touch-icon.png` is still the older blue mark.

**Type.** Figtree, self-hosted (`static/fonts`, the `@font-face` is inline in `base.html` with a hashed URL and a preload). Figtree's rupee sign is not in the Latin subset, so `figtree-rupee.woff2` (about 1 KB, only U+20B9) carries it; without it each phone would draw its own sign. Text inputs are 16px or more so iOS does not zoom.

## Page anatomy

Every list page opens the same way:

1. **Title row** (`.page-head.tall`): the title, and the month pill at the right where the page has a month. It is the same height on every page, so titles line up.
2. **Switcher** (full width, `.chips.seg`): Spend · Save, Asset · Liability, Expense · Income. Transactions and Settings have none.
3. **Head** (`.ready-hero`): a small label above one large figure, and one quiet line under it. Budgets: Ready to assign. Accounts: What you own / What you owe / Equity. Categories: Spent so far / Earned.
4. **The list**, in tiles.
5. **A dashed "+ Add …" row** (`.add-row`) at the end where something can be added.

Home is the exception by design: one number ("Left to spend"), a thin bar and then the transactions. Navigation is a bottom tab bar on phones (Home, Budgets, Accounts, Categories, with the "+" docked in the middle) and a sidebar from 60rem (new-transaction button, the same links, Transactions, Settings at the bottom). Pass `active` for the current section and `hide_fab=True` on form pages.

## The parts

| Part | What it is |
|---|---|
| **Tile** (`.tile`, `ul.card.list`) | A soft rounded surface with a hairline border and a hairline between rows. One tile per day in transaction lists, per group on Accounts and Budgets, per section in Settings. The tile rule is one block at the end of `style.css`. |
| **Row** | A name, one quiet second line, the figure at the right. Budgets rows add a bar under it; Categories show the biggest subcategories and the share; Accounts rows have no initials. Rows are links; destructive actions live on the detail page, not on rows. |
| **Month pill** | `‹ Oct 2026 ›` as plain text: two arrows around a native month picker laid invisibly over the month name (`partials/month_pill.html`). Pages that never look ahead pass `max`. |
| **Bottom sheet** | A `<dialog>` that slides up (a transaction's details, a category's budget, a goal, the Filter). It opens at once with grey placeholders and the content fades in over them. A press that starts inside never closes it. |
| **Toast** | A flash after saving. After saving or deleting an entry it carries **Undo**. |
| **Empty state** | A sentence and one pill button (`.empty-state`), without a box. |
| **Form** | Boxed fields in one card and **one full-width primary button, no Cancel** (the back link is the cancel; sheets keep theirs). |
| **Progress bar** | 3 px, full width of its row. Bars of the current month carry a small triangle under them showing how far through the month today is (`.pace`): a fill ahead of it is spending faster than the month passes. Over the plan is red. |
| **The "i"** | A faint round `i` beside Left to spend and Ready to assign opens, in place, the sum behind the figure with the person's own numbers (`partials/calc_info.html`, pure CSS `:has()`, no script). |

## The Add screen

The new-transaction page is the most used and the most designed:

- A large **amount** at the top. Its width follows what is typed (`--n`, a comma counts as about half a digit) and the rupee sign sits in front. On a phone nothing is focused (a script cannot open the keyboard); the grey `0.00` stays visible until the first digit, also while focused.
- A kind switcher, **Expense · Income · Transfer**, whose pill glides to the chosen button. The kind only narrows the account pickers.
- **From** and **To** tiles with the swap button on the seam between them. A side with one row has no ×; a split shows it on every row. Only "left to allocate" and "over" speak under a side.
- The **date is a chip** ("Today, 24 Oct"), the note a plain field, **Save & add another** a quiet underlined link under Save.
- **Payee chips**: one row on any width, chips that would not fit are hidden.

## Amounts

- **Typed amounts are cleaned as they are typed** (`cleanAmount` in `app.js`): digits, commas, one decimal point, a leading minus; leading zeros dropped; decimals stop at what the currency keeps. The form's amounts are grouped as typed (`groupAmount`: `1,24,500` for rupees) with the cursor staying after the same digits; the server strips commas.
- **Shown amounts**: ordinary spending has no minus sign, income is `+` and green, transfers plain; a real negative keeps its `−` in red. On an account's own page green and `+` mean what raises an asset or pays into a liability. For INR the whole part is grouped as lakhs and crores and large figures carry `₹` in front; other currencies are grouped in thousands with the code after.
- Amounts that touch the system's Opening Balances (`tx-system`) are muted and name only the other account.

## Motion

All in CSS unless noted, all off under reduced motion:

| What | How |
|---|---|
| Page arrival | main fades in over 140 ms; what is under the head rises 6 px (`rise-in`). Switching a chip uses the browser's page transition (`@view-transition`): the chosen chip glides while the head stays still. |
| Sheets and toasts | A sheet slides up in .25 s with a fading dim area (`@starting-style`); a toast rises in and fades out. |
| Bars | Fill from zero in .5 s on page load; a bar swapped in by assigning does not replay (`html[data-live]`). |
| Presses | Tappable rows dim while pressed, buttons dim and shrink 2 %. |
| Folds | Folding rows ease their height where the browser can (`interpolate-size`). |
| The saved row | After saving, the new row settles with a short rise and tint (`tx-new`). |
| Loading | A thin `.loadbar` shows while a request or page load is under way. Sheet placeholders are `.skeleton`. |

The browser tests run with reduced motion so measured positions never catch a page mid-rise.

## Offline and failure

`base.html` carries one hidden `#net-banner`. Offline shows "You're offline…"; a request that cannot reach the server, times out or answers 5xx says the entry is still on the page; a later success clears it. There is no offline queue. A form being sent cannot be sent twice.

## Adding to the design

1. Reuse a part from the table above; if none fits, ask whether the page needs the new thing at all.
2. Use tokens, and define any new token in all three blocks.
3. Keep tap targets at `--tap` and text inputs at 16px.
4. Put anything that depends on `app.js` under a browser test in `tests/browser/` (run Chromium and WebKit; WebKit is the closest to iOS Safari).
5. Update this page and `CLAUDE.md` when a part changes.

Next: [MCP and authentication](mcp-and-auth.md).
