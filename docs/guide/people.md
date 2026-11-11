# People: lending, borrowing, sharing a bill and settling up

Open **Settings › Your data › People** (or **People** in the sidebar on a wide screen). A person is someone you lend to, borrow from or share costs with. Everything you do with them is kept on their page, and what they owe you (or you owe them) is always worked out from your books.

## Adding someone

**Add person** asks for a name (up to 30 characters; two people can't share a name) and, if you like, a phone, email and note. Behind the scenes finode makes two accounts, **Due from Alice** (what she owes you) and **Due to Alice** (what you owe her). They never show on the Accounts page or in the pickers: you use them only through her page.

## A person's page

The big figure is what is owed: *Alice owes you ₹1,500.00*, or *You owe Alice*, or *All settled up*. Under it are four buttons: **Expense**, **Lend**, **Borrow** and **Settle** (Settle shows only while something is owed). They record nothing themselves: each one opens **+** (New transaction) with the person already filled in, and you finish it there like any other entry.

- **Open** lists each amount still owed, oldest first, with how much of it has been paid back. Tap one to see the entry it came from.
- **Activity** lists everything you did together. Tap an entry to see it or **Reverse** it.

## Money that was already owed

If someone owed you (or you owed them) before you started with finode, fill in **Already owes you, or is owed?** on **Add person**, or choose **Add an opening balance** in the **…** menu of someone already added. Say who owes whom, how much, and since when. It is added to your opening balances: none of your accounts or budgets change, and it can be paid back with **Settle** like anything else. To change it later, open it under **Activity** and tap **Edit**: you can change the amount, the day, the note and who owes whom. Once part of it has been paid back, the amount can't go below what was paid and who owes whom stays as it is.

## Lend, borrow and settle

All of it is a **Transfer** in **+** with a person on one side and one of your accounts on the other (the **Lend**, **Borrow** and **Settle** buttons on a person's page just open it for you). A person on the **To** side is money going to them; on the **From** side is money coming from them. A line under the form says what it will do before you save:

- Money to someone you owe pays back what you owe them first. Money from someone who owes you does the same. Only what is left over is new: a loan (to them) or a borrowing (from them).
- With nothing owed that way, all of it is a loan or a borrowing.
- A loan or borrowing is **not** spending or income, so your budgets don't change; the money simply leaves (or joins) Ready to assign.

**Settle** fills in what is owed and puts the person on the side that clears it. You can change the amount: paying less leaves the rest owed, paying more makes the extra a new borrowing or loan.

An entry you already recorded can become a loan too: open it, choose **Transfer**, and pick a person on one side. It keeps its date, tags and related link. To turn a loan back into an ordinary entry, edit it and pick an ordinary account instead of the person. Neither works once something has been paid back against it.

## A gift

A gift to or from a person is an ordinary expense or income. In the **Payee** field type **@** and choose the person: the entry is saved in their **Activity** as a gift and nothing is owed. Type over the name, or tap the cross, to take them off again. It can be edited and deleted like any other entry.

## Record an entry two ways

Under **Expense**, **Income** and **Transfer** there is a second switch: **Simple** and **Split**. The sides are named for what they are: an expense is **Paid from** and **Spent on**, an income is **Earned from** and **Paid into**, a transfer is **From** and **To**.

- **Simple** is the accounts and categories for the whole amount: one on each side, or several that add up to it, for example two categories. Typing less than the amount in a row adds the next one by itself.
- **Split** shares the amount with people.
  - **Expense:** a bill you share. Choose the category and the account you paid from, choose **Equally**, **Amounts**, **%** or **Shares**, then tap **Add people** and tick the people who share it (the list has a search; tap the cross on a row to take someone out). Only the people you added are shown. A box next to each person takes their amount, percentage or weight. If someone else paid some of it, open **Someone else paid some of it**: it lists only the people in the bill. Under the form you see each share, your own share (the only part your budget sees) and who owes whom.
  - **Income:** money that came in, part of it not yours (rent you collect for a co-owner). Choose the category it is earned under and the account it was paid into, tap **Add people** to choose them, and type each person's part in the box next to their name. Only the rest is your income; the parts you hold for people are money you owe them. If someone else received some of it for you, open **Someone else received some of it for you**: they now owe you that amount. A person is on one side only.

A transfer has no such switch: people are simply listed with your accounts on it (see above).

An entry you already recorded can change between the two: open it, choose another way and save. It keeps its date, tags and related link. Editing a shared bill or shared income later opens on **Split** as you entered it. None of this works once a share has been paid back. **Expense** on a person's page opens the same screen with that person ticked.

## How a shared bill is worked out

**Split** on an expense divides the amount like this:

- **Equally**,
- **Amounts** (each person's amount; they must add up to the total),
- **%** (they must make 100),
- **Shares** (weights: 2 and 1 means two thirds and one third).

The bill must be fully paid for before it can be recorded. Pennies that don't divide evenly go to the first people, so the shares always add up exactly.

If a friend paid for you and you hadn't paid anything, nothing leaves your accounts; the share counts against your budget when you pay them back.

## When you owe each other

Nobody is ever owed both ways. If you lend someone money while you owe them, or a bill they paid makes you owe them while they owe you, finode evens the two out at once: the smaller side is cleared in full and the same amount of the larger, oldest first. It shows in **Activity** as *Evened out*. None of your accounts or budgets change, and it goes by itself if you reverse one of the entries it settled.

## Undoing

**Reverse** (in an entry's sheet) removes a loan, a shared expense or a settlement for good, as if it never happened. It can't be reversed while something has been paid back against it: reverse the payment first. Entries made this way can't be edited or deleted from Transactions; their sheet there points to the person's page instead.

## Archiving and removing

From the **…** menu: **Archive** hides someone you're done with (only when nothing is owed either way; their history stays and you can restore them under the **Archived** chip). **Remove** deletes someone you never did anything with, and archives anyone else.

Assistants and the JSON API do all of this too (see the [API](../developer/api.md)).
