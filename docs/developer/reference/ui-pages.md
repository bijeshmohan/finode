# The app: screen by screen

What each screen of the finode app shows and how it behaves. Each screen lives in `frontend/src/features/<area>/` and reads one view endpoint (`/api/views/…`, listed in [api.md](../api.md)); what a row, a total or a sentence says is worked out on the server, in the `services/*_view.py` modules and `services/transaction_rows.py`. Dates in headings are when a decision was made (most on the server-rendered pages the app replaced on 2026-11-17, kept as they were). The look and the shared parts are in [ui-look.md](ui-look.md); the rules summary is in `AGENTS.md`.

## Home (`/`, `features/home`)

One number: **Left to spend in <month>** from the budget, with "Spent so far X of Y" under a thin bar with the pace notch, or "Over budget" in red; until something is assigned or carried in, the month's spending with a way to set up the budget. The label (with the "i") and **the month pill** share the top row (never a month ahead; a past month shows its own figures, without the notch). No box around the figure (2026-10-20), no columns (2026-10-23), no overspent line (2026-10-24), no net worth.

Then the month's entries under "Transactions": **the first 8, then "Show more" loads the rest of the month in place** (a day is never split between chunks; `TransactionService.page`); "View all ›" opens Transactions on that month. Entries dated ahead are not on Home. With nothing recorded yet Home shows the **first steps** (`GetStarted`: rows you tap, the next step's number filled in, finished ones ticked, "Get started · N of 3"). From 60rem the column is centred in the space beside the sidebar.

## Add and Edit (`/transactions/new`, `/transactions/{id}/edit`, `features/entry`)

`EntryScreen`, saved through `/api/entries` (the server decides what it records: `services/entry.py`). Where it starts comes from `/api/views/entry-form` (blank, from an account's or a category's page, Repeat, Related, a card bill to pay, money to or from a person, or an entry being edited).

- **The kind** first (Expense · Income · Transfer, a switcher whose pill glides), then **the amount**: a bare figure, the rupee sign against it, grouped as it is typed (`1,24,500`), focused at once only on a computer.
- **Two tiles** whose headings follow the kind (`components/lines/kinds.ts`): Expense **Paid from / Spent on**, Income **Earned from / Paid into**, Transfer **From / To** (2026-11-04). Swap exchanges them on a transfer; an expense has no swap.
- **The rows** (`components/lines/Lines`): a side lists its accounts or categories as slim rows (a glyph, the name, "Posts 18 Oct" only when the line's day differs from the entry's, its amount only when it differs from the total) and one empty row while something is left to allocate ("450.00 left"). Typing less than the total on a row adds a row with the remainder (`components/lines/rows.ts`). Tapping a row opens **the picker** (`Picker`: a search, group headings (one per account type, in the person's order), an account's balance, the other side's account greyed, "＋ New account" / "＋ New category", which open `QuickAdd`: an account picks one of the four types with the **Kind** chips, each with its icon); one tap picks and closes. A chosen row has a **settings glyph** that opens `RowSettings`: its amount and, on an account of an entry, the day it posts (a native date, not before the entry's day), a **Done** pill and a red **Remove** (2026-11-02). 
- **Payee** (`PayeeField`): chips of the people you pay most, **only while something is typed** (names only since 2026-11-01: a chip fills the payee and moves on to the amount, never an account or a category), one row on any width, "Payee or Merchant?" as the placeholder. Typing `@` names a person (see [people.md](people.md)). A new entry starts with **no account and no category chosen** (2026-10-24).
- **The date** is a chip ("Today, 24 Oct") over the native date picker; **the note** is a plain field with its # button for tags (`NoteAndTags`).
- **Split** (expense and income): who a bill is shared with and how, who paid, with the server's preview as you type (`ShareEditor`, `SharePreview`, `/api/views/entry-share-preview`; see [people.md](people.md)).
- **Related**: an entry can name the one it relates to (a refund of a purchase); the chip removes the link.
- One full-width **Save** ("Save changes" when editing). A refusal shows the server's words and keeps what was typed. Delete, on Edit, is for good and asks first.

## Transactions (`/transactions`, `features/transactions`)

A title row with the **month pill** at the right (never a month ahead), then "N transactions" (with a filter set and every match going one way, "· ₹X spent|earned") and one **Filter** button ("Filter · N" when set). **The filter sheet** has three lists you can search: **Account** (with the accounts inside it), **Category** (with the ones inside it) and **Merchant** (an exact payee, most used first), plus tags; what is set shows under the line with a ✕ (2026-10-23). There is no search box (2026-10-20) and no kind switcher.

The list shows **25 entries, then "Show more"** in place. **Entries dated ahead are not history**: in the current month they sit in **one card at the top** (`UpcomingCard`: closed, "N upcoming · X in all"; opened, soonest first), which a filter opens only when no history matches. Days of two or more **opening balances fold** into one row, "Opening balances · N accounts" (2026-11-05). A row that touches the system's Opening Balances has a muted title and figure.

**A row opens the details sheet** (`TransactionSheet`, `/api/views/transactions/{id}`), on Home and on an account's or a category's page too: the payee (else where the money went), date and amount, the accounts by kind (every row of a split), the note and tags, then behind one **More** row the related entries and who added it (an assistant or a recurring rule, in violet; nothing for the app, the API or an import), and **Edit** with Repeat, Related and Delete under it (Delete red; it asks first and is for good). A related entry's pill opens the original, the row its own sheet. On a wide screen with a mouse the sheet is a panel beside the list.

## Accounts (`/accounts`, `features/accounts`)

**One page, no switcher, no Asset/Liability/Equity** (the type names stay out of the app; 2026-11-09). The title and one quiet line ("N accounts"; **no net worth and no budget key** since 2026-11-22: every account is in the budget), then a **Pinned** row when anything is pinned (2026-11-10), then one **type** per section with room between them and a heading larger than a card's name, led by the type's icon (the name, and one quiet line: the type's total, "X owed" for what you owe, and "N accounts"), over **a row of cards that scrolls sideways** on its own (the next card peeking in; the page itself never scrolls sideways). With a mouse or trackpad (`hover: hover` and `pointer: fine`) the row shows a thin scrollbar to drag, since a mouse cannot swipe and its wheel scrolls the page; touch screens keep it hidden (2026-11-21). The four types come in the person's order (Settings › Order of account types; it starts Bank Account, Cash, Credit Card, Prepaid Wallet) and always show, empty ones too; Equity and the people's accounts are not listed. An empty ledger shows the four shelves, each adding an account of its type.

**A card** (`AccountCard`, all the same size) carries the name, a small pin when pinned, the balance and **a quiet line only when there is something to say**: "Bill due 15 Nov" (red when due soon; "Bill overdue" once past), else "No entry since 12 Sep" after 30 days, else "No entries yet". The last card of a row is a dashed **"+ Add account"** of that type (`/accounts/new?type=…`). There are no groups of one's own. Every open account is listed; closed ones wait behind **Load more**.

**An account's page** (`AccountPage`, `/api/views/accounts/{id}`): the type's icon and the name with an "i" when it has a description (the description and the "…" menu each close the other), its type under it (never "Assets"), a **pin button**, the balance and, for a Credit Card with bill days, **the bill** (`CardBill`: what is left of the latest statement and when it is due, with **Pay bill**, which opens Add with the card and the amount). Then what is dated ahead in one card, and the entries by day with the running balance, newest first, 30 at a time with **Load more**. **A type's page** shows its accounts as the same cards, an Add account card (`add_url`) and then their transactions together. Edit, Close / Reopen are in an account's menu. The account form (`AccountForm`) chooses the **type** with the switcher (the four in the person's order; nothing chosen unless the link says), has no budget switch, and asks for the statement and due days only for a Credit Card; editing keeps the type. Closing is refused while the account holds a balance or a running rule uses it.

## Categories (`/categories`, `features/categories`)

One month (never ahead), **Spending · Earning** as the switcher, the month's total as one figure, and a **ranked list**: one row per category (one flat list since 2026-11-23) led by its icon, biggest first, with its share ("13% of spending", `<1%`, `0%`); every open category is listed, with nothing in the month too. **No chart and no colours** (2026-10-19). A dashed "+ Add category" ends the page.

**A category's page** (`CategoryPage`): the month pill, the month's total, then the month's entries. The "+" adds an entry for the category and comes back here. The page shows the category's icon beside its name. The form (`CategoryForm`) has a name, an **Icon** field (`IconPicker`; a new category is not sent until one is chosen; the built-in Uncategorised offers none) and a note (no group to choose: categories are one flat list since 2026-11-23, and subcategories, "Everything else" and "+ Add subcategory" went with the groups). For a category the word is **Delete**: an unused one goes for good; one with entries or a rule is closed instead and "Restore category" brings it back.

## Budgets (`/budget`, `features/budget`)

See [budget.md](budget.md) for the rules. **Ready to assign** with its "i", **Copy last month's amounts**, then the categories, one ranked list (flat since 2026-11-23): one row each (`BudgetRows`: the category's icon, the name, "of 25,000.00", then "all spent" or a red "overspent", and the bar; rows carry no pace notch since 2026-11-04). A row opens **the category's sheet** (`CategorySheet`: what is left, what is assigned this month with Save, which works on the first tap even as the keyboard opens, and Move money); on a wide screen with a mouse it is a panel. The old group pages' addresses (`/budget/groups/{id}`, `/budget/group/{id}`) land on Budgets. **Move money** (`/budget/move`, `MovePage`): From and To in our own picker, each with what it has left. **Coming up** (`/budget/coming-up`, `ComingUpPage`): what is due to the budget's accounts, by day, opened from the sum on Budgets. With no account in the budget the page says one sentence and offers "Choose accounts".

## The bell (`features/todo`)

The to-do bell sits in the top bar (in the sidebar on a wide screen) with a count only when something needs a decision: a bill due soon (with **Pay bill**), a rule that could not record. Each item carries its fix.

## People (`/people`, `features/people`)

See [people.md](people.md): the list (All · Owe you · You owe, and Archived once someone is), a person's page with the short-hands to Add (Lend, Settle), what is open and what happened, each entry in its sheet (reversing asks first), the person form with an opening balance, and the opening balance's own form.

## Recurring (`/recurring`, `features/recurring`)

A calm list of the shared row (2026-10-27): the payee, one quiet line ("Every month · next 1 Nov", "· paused", "· ended", or the red "Couldn't record: …") and the amount; paused and ended rules under "Paused", muted; a dashed "+ New recurring". **The form** (`RecurringForm`) is the Add screen's rows (a split or a plain rule; no posting day of their own, no people), the payee and tags, the repeat (its unit named), the start and an end-date chip that clears; a hint about a past start shows only while the start is past. Editing offers Skip next, Pause / Resume and Delete.

## Tags (`/tags`, `features/tags`)

Plain rows in one tile: the blue `#tag` and how many entries carry it. A tag's sheet has its uses and last day, **View entries** (Transactions filtered by it), Rename, Merge into… and Delete.

## Settings (`/settings`, `features/settings`)

**One screen for the person and the app** (2026-10-23): the profile row (the name, the email), **Preferences** (currency, appearance: auto, light or dark, kept in this browser, and **Order of account types**: the four with move-up and move-down buttons, each move saved at once, `TypeOrderRow`), **Your data**, **AI assistants**, About (feedback, the test notice) and **Sign out** as a red row. A row's value sits beside its chevron. Per-person settings are typed columns on `profiles` (a column, a migration, a `ProfileUpdate` field), never a key-value store or Supabase `user_metadata`; the look is per browser (`lib/theme.ts`).

**Your data** (`/profile/data`, `DataPage`): Export and Backup download from the API; Import and Restore show a preview first and then confirm (`ImportRestore`); under "Erase or leave", **Erase** and **Delete my account** as red rows, each typed out to confirm and accepted only from the app's own session. **AI assistants** (`/profile/assistants`, `AssistantsPage`): what is connected and its access (change it, revoke a token, disconnect an app), Sign in with Claude, a token (its secret shown once), and the setup snippets (`McpSetup`). **The consent screen** (`/oauth/consent`, `features/consent`) is where Supabase sends a person who connects an assistant: the app's name, the access levels in words, Allow or Deny (see [assistants.md](assistants.md)).

## Signing in (`features/auth`)

Sign in, sign up (invite only), forgotten password and reset sit on a bare screen: no tab bar and **no card**, the form centred under a larger wordmark (2026-11-05). Signing in goes back where the person was going (only inside the app: `lib/safeNext.ts`), else Home. The old addresses `/login` and `/signup` still open them.
