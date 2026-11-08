# People: lending, borrowing, sharing a bill and settling up

Open **Settings › Your data › People** (or **People** in the sidebar on a wide screen). A person is someone you lend to, borrow from or share costs with. Everything you do with them is kept on their page, and what they owe you (or you owe them) is always worked out from your books.

## Adding someone

**Add person** asks for a name (up to 30 characters; two people can't share a name) and, if you like, a phone, email and note. Behind the scenes finode makes two accounts, **Due from Alice** (what she owes you) and **Due to Alice** (what you owe her). They never show on the Accounts page or in the pickers: you use them only through her page.

## A person's page

The big figure is the difference: *Alice owes you ₹1,500.00*, or *You owe Alice*, or *All settled up*. When she owes you some things and you owe her others, both amounts are written under it. Three buttons: **Add expense**, **Lend or borrow** and **Settle up**.

- **Open** lists each amount still owed, oldest first, with how much of it has been paid back. Tap one to pay off just that one.
- **Activity** lists everything you did together. Tap an entry to see it or **Reverse** it.

## Money that was already owed

If someone owed you (or you owed them) before you started with finode, fill in **Already owes you, or is owed?** on **Add person**, or choose **Add an opening balance** in the **…** menu of someone already added. Say who owes whom, how much, and since when. It is added to your opening balances: none of your accounts or budgets change, and it can be paid back with **Settle up** like anything else. To change it later, open it under **Activity** and tap **Edit**: you can change the amount, the day, the note and who owes whom. Once part of it has been paid back, the amount can't go below what was paid and who owes whom stays as it is.

## Lend or borrow

Choose what happened: *I lent money*, *I borrowed money*, *I paid an advance*, *They paid an advance*, *I gave a gift* or *They gave me a gift*, then the amount, your account and the day. A loan or borrowing is **not** spending or income, so your budgets don't change; the money simply leaves (or joins) Ready to assign. A gift is spending (or income) under a category you pick, and nothing is owed.

You can also start a loan from **+** (New transaction): choose **Transfer**, then pick a person on one side and one of your accounts on the other. A person on the **To** side is money you lent; on the **From** side is money you borrowed. Paying back or being paid back is always done from the person's page with **Settle up**.

An entry you already recorded can become a loan too: open it, choose **Transfer**, and pick a person on one side. It keeps its date, tags and related link. To turn a loan back into an ordinary entry, edit it and pick an ordinary account instead of the person. Neither works once something has been paid back against it.

## Record an entry two ways

Under **Expense**, **Income** and **Transfer** there is a second switch: **Simple** and **Split**. The sides are named for what they are: an expense is **Paid from** and **Spent on**, an income is **Earned from** and **Paid into**, a transfer is **From** and **To**.

- **Simple** is the accounts and categories for the whole amount: one on each side, or several that add up to it, for example two categories. Typing less than the amount in a row adds the next one by itself.
- **Split** shares the amount with people.
  - **Expense:** a bill you share. Choose the category and the account you paid from, choose **Equally**, **Amounts**, **%** or **Shares**, and tick the people who share it. A box next to each person takes their amount, percentage or weight. If someone else paid some of it, open **Someone else paid some of it**. Under the form you see each share, your own share (the only part your budget sees) and who owes whom.
  - **Income:** money that came in, part of it not yours (rent you collect for a co-owner). Choose the category it is earned under and the account it was paid into, and type each person's part in the box next to their name. Only the rest is your income; the parts you hold for people are money you owe them. If someone else received some of it for you, open **Someone else received some of it for you**: they now owe you that amount. A person is on one side only.
  - **Transfer:** lending, borrowing and paying back. People are listed with your accounts only on this tab, and one person goes on one side.

An entry you already recorded can change between the two: open it, choose another way and save. It keeps its date, tags and related link. Editing a shared bill, shared income or a loan later opens on **Split** as you entered it. None of this works once a share has been paid back. **Add expense** on a person's page opens the same screen with that person ticked.

## How a shared bill is worked out

**Split** on an expense divides the amount like this:

- **Equally**,
- **Amounts** (each person's amount; they must add up to the total),
- **%** (they must make 100),
- **Shares** (weights: 2 and 1 means two thirds and one third).

The bill must be fully paid for before it can be recorded. Pennies that don't divide evenly go to the first people, so the shares always add up exactly.

If a friend paid for you and you hadn't paid anything, nothing leaves your accounts; the share counts against your budget when you pay them back.

## Settle up

Choose who pays (*Alice pays you* or *You pay Alice*), the amount and your account. finode shows which amounts it clears, oldest first, and what's still owed afterwards. You can pay more than is owed only by saying what the rest is (a loan, an advance or a gift); it never disappears silently. To pay off one particular amount, open it from **Open** on the person's page.

## When you owe each other

If someone owes you and you owe them (a loan and a borrowing, say), the page shows **Even** and the list says "Even · 23,000.00 each way". Tap **Net off** on their page to clear the two against each other: the smaller side is cleared in full and the same amount of the larger, oldest first. None of your accounts or budgets change, and you can reverse it from **Activity**.

## Undoing

**Reverse** (in an entry's sheet) removes a loan, a shared expense or a settlement for good, as if it never happened. It can't be reversed while something has been paid back against it: reverse the payment first. Entries made this way can't be edited or deleted from Transactions; their sheet there points to the person's page instead.

## Archiving and removing

From the **…** menu: **Archive** hides someone you're done with (only when nothing is owed either way; their history stays and you can restore them under the **Archived** chip). **Remove** deletes someone you never did anything with, and archives anyone else.

Assistants and the JSON API do all of this too (see the [API](../developer/api.md)).
