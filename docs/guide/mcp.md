# Using finode from an AI assistant

finode has an **MCP server**, so an assistant such as Claude can read your books and, if you allow it, record things for you. You stay in control: you choose the access level for each connection, can change it at any time, and can disconnect.

## What an assistant can do

**Read** (always available on a connection):

| Tool | Answers |
|---|---|
| `get_status` | what this connection may do, today's date, how much room is left today, when your books last changed |
| `get_transaction_history`, `recent_changes` | what happened to an entry, what each edit changed and who did it (you, the app, an import or an assistant); what changed lately |
| `payee_defaults` | which accounts you usually use for a payee, so an assistant books it the way you do |
| `get_overview` | net worth, your currency, the shape of your books |
| `list_accounts`, `get_account` | your accounts (with their ids, type, whether they are in the budget and what they are for) and one account's balance and recent activity |
| `search_transactions`, `get_transaction` | find and open entries; a search also counts and totals everything it matched |
| `spending_breakdown` | where the money went, by account |
| `get_budget` | the month's budget: Ready to assign, each category's assigned, spent and left, and your goals |
| `list_recurring` | your recurring rules |
| `list_deleted_transactions` | deleted transactions that can still be brought back |
| `check_books` | re-checks that every transaction balances |

**Write** (only on a read & write connection): `record_transaction`, `record_split`, `record_transactions` (up to 50 entries at once, all saved or none, safe to send again when each has a source and reference), `update_transaction`, `delete_transaction`, `create_account`, `create_recurring`, `stop_recurring`, `resume_recurring`, `skip_recurring_occurrence`, `restore_transaction`, `create_goal`, `update_goal`, `delete_goal`, `assign_to_category`, `assign_to_goal`, `use_goal`, `move_budget_money`, `copy_budget_from_previous_month`. Recording or changing a transaction can link it to an earlier one (`related_to`, for a refund or reversal). They also take `source`, `external_id` and `source_url` for an entry that comes from outside finode (a bank message, a mail): sending the same source and reference again returns the entry already made instead of a copy, and `search_transactions` finds an entry by them. `record_transaction`, `record_split`, `record_transactions`, `update_transaction` and `delete_transaction` also take `dry_run`: finode checks every rule and tells the assistant what would be saved without saving anything, which works on a read-only connection too, so an assistant can show you a change before you allow it.

There is also a ready-made prompt, `monthly_review`, which asks the assistant for a short review of a month.

What it **cannot** do: delete or edit accounts, change settings, make tokens, or reach another person's data. On a read-only connection the write tools are listed but refuse, and the assistant tells you to allow changes.

Anything an assistant records is marked on the transaction ("Added by Claude" in blue), and the edit page says who added and last changed it.

You can refer to accounts by their path (`Assets:Bank:HDFC`) or by a unique end (`HDFC`). Amounts are in your currency, as plain numbers.

## Connecting

Open **Profile › AI assistants**. There are two ways.

### A. Connect by signing in (Claude on the web or your phone)

1. In the app that offers custom connectors (for example Claude), add a connector using the address shown under *Connect by signing in*. Use the Copy button.
2. You are sent to finode (sign in if asked) and see a consent page: choose **read only** or **read & write**.
3. Done. The connection is listed under *Connected*.

### B. Connect with a token (Claude Code, Claude Desktop, Cursor, …)

1. Under *Connect with a token*, give it a **name** (where you will use it; it shows next to everything the assistant records) and choose the access level.
2. **Create token.** A box titled *<name> is ready* shows the secret once, with a **Copy token** button; copy it now, because finode keeps only a fingerprint and cannot show it again. The secret starts with `fin_`.
3. Use the setup instructions on the page. For Claude Code, for example:

   ```bash
   claude mcp add --transport http finode <the address on the page> --header "Authorization: Bearer <your token>"
   ```

   Other clients take the address and an `Authorization: Bearer …` header; the page shows ready-made snippets.

## Changing or removing access

On the same page every connection has **Allow changes** / **Make read only**, and a way to **disconnect** or revoke it. A revoked token stops working immediately. Disconnecting an app also revokes its sign-in with Supabase.

## Tips

- Start with a **read only** connection and ask questions ("what did I spend on food last month?", "how much is Ready to assign?").
- Before letting an assistant record anything, ask it to tell you what it is going to record. Deleting a transaction is marked as destructive, but you can bring one back from *Recently deleted* on the Transactions page.
- Your data is only reachable with a valid token or approved connection, and a token works **only** on the assistant endpoint, never on the website or the JSON API.
