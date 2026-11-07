# People: lending, borrowing, sharing a bill and settling up

Open **Settings › Your data › People** (or **People** in the sidebar on a wide screen). A person is someone you lend to, borrow from or share costs with. Everything you do with them is kept on their page, and what they owe you (or you owe them) is always worked out from your books.

## Adding someone

**Add person** asks for a name (up to 30 characters; two people can't share a name) and, if you like, a phone, email and note. Behind the scenes finode makes two accounts, **Due from Alice** (what she owes you) and **Due to Alice** (what you owe her). They never show on the Accounts page or in the pickers: you use them only through her page.

## A person's page

The big figure is the difference: *Alice owes you ₹1,500.00*, or *You owe Alice*, or *All settled up*. When she owes you some things and you owe her others, both amounts are written under it. Three buttons: **Add expense**, **Lend or borrow** and **Settle up**.

- **Open** lists each amount still owed, oldest first, with how much of it has been paid back. Tap one to pay off just that one.
- **Activity** lists everything you did together. Tap an entry to see it or **Reverse** it.

## Lend or borrow

Choose what happened: *I lent money*, *I borrowed money*, *I paid an advance*, *They paid an advance*, *I gave a gift* or *They gave me a gift*, then the amount, your account and the day. A loan or borrowing is **not** spending or income, so your budgets don't change; the money simply leaves (or joins) Ready to assign. A gift is spending (or income) under a category you pick, and nothing is owed.

You can also start a loan from **+** (New transaction): choose **Transfer**, then pick a person on one side and one of your accounts on the other. A person on the **To** side is money you lent; on the **From** side is money you borrowed. Paying back or being paid back is always done from the person's page with **Settle up**.

## Share an expense

**Add expense** takes the total, what it was for, a category, the day and your account, and how to split it:

- **Equally**,
- **Amounts** (each person's amount; they must add up to the total),
- **%** (they must make 100),
- **Shares** (weights: 2 and 1 means two thirds and one third).

Tick the people who share it. Under the form you see each share, **your share** (the only part your budget sees), and who owes whom. If someone else paid some of the bill, open **Someone else paid some of it** and say how much each paid. The bill must be fully paid for before it can be recorded. Pennies that don't divide evenly go to the first people, so the shares always add up exactly.

If a friend paid for you and you hadn't paid anything, nothing leaves your accounts; the share counts against your budget when you pay them back.

## Settle up

Choose who pays (*Alice pays you* or *You pay Alice*), the amount and your account. finode shows which amounts it clears, oldest first, and what's still owed afterwards. You can pay more than is owed only by saying what the rest is (a loan, an advance or a gift); it never disappears silently. To pay off one particular amount, open it from **Open** on the person's page.

## Undoing

**Reverse** (in an entry's sheet) removes a loan, a shared expense or a settlement for good, as if it never happened. It can't be reversed while something has been paid back against it: reverse the payment first. Entries made this way can't be edited or deleted from Transactions; their sheet there points to the person's page instead.

## Archiving and removing

From the **…** menu: **Archive** hides someone you're done with (only when nothing is owed either way; their history stays and you can restore them under the **Archived** chip). **Remove** deletes someone you never did anything with, and archives anyone else.

Assistants and the JSON API do all of this too (see the [API](../developer/api.md)).
