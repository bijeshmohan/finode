# The design system

finode looks the way it does on purpose: **calm, minimal and quick to enter**. This page describes the look, the small set of parts every screen is built from, the motion, and the rules that keep new screens consistent. The parts are React components in `frontend/src/components/`, each with its CSS Module. [The app](web-ui.md) covers how screens get their data.

## Principles

1. **Phones first.** Every page is one column that works on a phone; from 60rem up a fixed sidebar replaces the top bar and tab bar and the column is centred in the space beside it. Nothing floats over the page.
2. **Fewer boxes.** Removing something or adding whitespace is preferred to adding a border, badge or card. A box earns its place only when it groups things that need telling apart.
3. **Colour means money.** Green and red appear only for money coming in or going out (and for an overspent category or an error). Actions are royal-blue ink (`#2b3a9e` in light, periwinkle in dark), and so are the progress bars. Violet marks what was added automatically (an assistant or a recurring rule).
4. **One of each part.** There is one switcher, one row, one tile, one sheet, one empty state. New pages reuse them; they do not draw their own.
5. **Calm motion.** Short, quiet transitions that explain a change (a chip gliding, a sheet rising). All of it switches off under `prefers-reduced-motion`.
6. **Nothing is lost on a failed save.** Forms are never cleared on an error, and the page says the entry is still there.

## Tokens

The tokens are CSS variables in `frontend/src/styles/tokens.css`, loaded first by `main.tsx`. Style with tokens only, never literal colours (the white switch knob is the one exception).

| Group | Tokens |
|---|---|
| Surfaces and text | `--bg`, `--surface`, `--surface-2`, `--text`, `--muted`, `--faint` |
| Lines | `--border`, `--field-border` (stronger in dark so empty fields show), `--tile-border` |
| Action | `--accent`, `--accent-hover`, `--accent-soft`, `--on-accent` |
| Meaning | `--positive`, `--negative`, `--danger`, `--danger-soft`, `--warn`, `--warn-soft`, `--auto` |
| Shape and size | `--radius` (20px, tiles and sheets), `--radius-sm` (14px, fields), `--tap` (44px), `--topbar-h`, `--tabbar-h`, `--sidebar-w`, `--bar-h` (3px, every progress bar) |

**Dark mode.** There are three blocks: the light tokens on `:root`, an automatic `prefers-color-scheme: dark` block, and a manual `[data-theme="dark"]` block. The two dark blocks must define the same tokens (a test compares them). The choice is per browser (`lib/theme.ts`, in `localStorage`), applied by `index.html` before the first paint. `favicon.svg` is royal ink, periwinkle in dark; `apple-touch-icon.png` is still the older blue mark.

**Type.** Anek Latin, self-hosted (`frontend/src/styles/fonts/anek-latin.woff2`, one variable file with weight 400–700 and width 75–100 %, Latin plus the rupee sign; the `@font-face` is in `styles/base.css`, and the build gives the file a hashed name). The big figures use the condensed width (`font-stretch: 75%`); see "The passbook look" in `reference/ui-look.md`. Text inputs are 16px or more so iOS does not zoom.

## Page anatomy

Every list page opens the same way:

1. **Title row** (`components/Page.module.css`): the title, and the month pill at the right where the page has a month. It is the same height on every page, so titles line up.
2. **Switcher** (full width, `Chips`): Spending · Earning on Categories. Accounts, Budgets, Transactions and Settings have none.
3. **Head**: a small label above one large figure, and one quiet line under it. Budgets: Ready to assign. Accounts: Net worth. Categories: Spent so far / Earned.
4. **The list**, in tiles.
5. **A dashed "+ Add …" row** at the end where something can be added.

Home is the exception by design: one number ("Left to spend"), a thin bar and then the transactions. Navigation is a bottom tab bar on phones (Home, Budgets, Accounts, Categories, with the "+" docked in the middle) and a sidebar from 60rem (new-transaction button, the same links, Transactions, Settings at the bottom). The "+" stays on every screen, the Add and Edit screens included (2026-11-16).

## The parts

| Part | What it is |
|---|---|
| **Tile** (`Tile`) | A soft rounded white slip (a hairline border in dark only) with a hairline between rows. One tile per day in transaction lists, per group on Budgets, per section in Settings. |
| **Row** (`Row`) | A name, one quiet second line, the figure at the right. Budgets rows add a bar under it; Categories show the biggest subcategories and the share; Accounts rows have no initials. Rows open a screen or a sheet; destructive actions live there, not on rows. |
| **Month pill** (`MonthPill`) | `‹ Oct 2026 ›` as plain text: two arrows around a native month picker laid invisibly over the month name. Screens that never look ahead stop at this month. |
| **Bottom sheet** (`Sheet`) | A `<dialog>` that slides up (a transaction's details, a category's budget, the Filter, the pickers), above the soft keyboard while a field in it has focus. A press that starts inside never closes it. On a wide screen with a mouse a transaction's details are a panel beside the list. |
| **Toast** | A short message after saving or deleting. |
| **Empty state** (`EmptyState`) | A sentence and one pill button, without a box. |
| **Form** | Boxed fields in one card and **one full-width primary button, no Cancel** (the back link is the cancel; sheets keep theirs). |
| **Progress bar** | 3 px (`--bar-h`), full width of its row. Bars of the current month carry a small triangle under them showing how far through the month today is (`pace`): a fill ahead of it is spending faster than the month passes. Over the plan is red. |
| **The "i"** (`CalcInfo`) | A faint round `i` beside Left to spend and Ready to assign opens, in place, the sum behind the figure with the person's own numbers. |

## The Add screen

The Add screen (`features/entry`, described in full in `reference/ui-pages.md`) is the most used and the most designed:

- A large **amount** at the top, a bare figure: its width follows what is typed and the rupee sign sits right against it. On a phone nothing is focused (that would raise the keypad over the screen); the grey `0.00` stays until the first digit.
- A kind switcher, **Expense · Income · Transfer**, whose pill glides to the chosen button. The kind only narrows the account pickers.
- **From** and **To** tiles (their headings follow the kind: Paid from / Spent on…). A side lists its rows; a chosen row's settings glyph opens its amount, its day and Remove. Only "left to allocate" and "over" speak under a side.
- The **date is a chip** ("Today, 24 Oct"), the note a plain field, and the form ends with Save alone.
- **Payee chips**: only while typing (nothing for an empty field), one row on any width, chips that would not fit are hidden; they go once one is chosen.

## Amounts

- **Typed amounts are cleaned as they are typed** (`lib/amount.ts`): digits, commas, one decimal point; leading zeros dropped; decimals stop at what the currency keeps. They are grouped as typed (`1,24,500` for rupees) with the cursor staying after the same digits; the app sends them without commas and the server checks again.
- **Shown amounts**: ordinary spending has no minus sign, income is `+` and green, transfers plain; a real negative keeps its `−` in red, and in a large figure the minus sits after the rupee sign, right in front of the digits (`₹−1,200.00`, never `−₹1,200.00`: the small raised `₹` would leave the minus adrift). On an account's own page green and `+` mean what raises an asset or pays into a liability. For INR the whole part is grouped as lakhs and crores and large figures carry `₹` in front; other currencies are grouped in thousands with the code after.
- Amounts that touch the system's Opening Balances are muted and name only the other account.

## Motion

All in CSS, all off under reduced motion:

| What | How |
|---|---|
| Sheets | A sheet slides up with a fading dim area (`@starting-style` on the dialog); on a wide screen it rises gently. |
| Toasts | A toast rises in and fades out. |
| Switchers | The chosen pill glides to its new place (the kind switcher on the Add screen, the Split's ways of sharing). |
| Chevrons | A fold's chevron turns as it opens. |

The browser tests run with reduced motion so measured positions never catch a screen mid-move.

## Offline and failure

`frontend/src/app/Offline.tsx` shows "You're offline…" while the device has no connection. A save that cannot reach the server or that the server fails says so in plain words, and the form keeps what was typed; the server's own words show only when it gave them as JSON. There is no offline queue.

## Adding to the design

1. Reuse a part from the table above; if none fits, ask whether the page needs the new thing at all.
2. Use tokens, and define any new token in all three blocks of `tokens.css`.
3. Keep tap targets at `--tap` and text inputs at 16px.
4. Put anything that needs a real browser under a browser test in `backend/tests/e2e/` (run Chromium and WebKit; WebKit is the closest to iOS Safari); the rest is Vitest beside the component.
5. Update this page and `docs/developer/reference/ui-look.md` when a part changes.

Next: [MCP and authentication](mcp-and-auth.md).
