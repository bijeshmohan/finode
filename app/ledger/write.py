import re
from datetime import date

from .model import AccountDecl, LedgerTransaction


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def write(accounts: list[AccountDecl], transactions: list[LedgerTransaction], generated: date) -> str:
    """Render a journal that ledger and hledger read as-is; amounts are debit positive."""
    out = [f"; finode export, {generated.isoformat()}", ""]
    for decl in accounts:
        out.append(f"account {decl.name}")
        if decl.note:
            out.append(f"    note {_one_line(decl.note)}")
    if accounts:
        out.append("")
    for transaction in transactions:
        # A ';' after whitespace would start a comment when the file is read back.
        payee = re.sub(r"\s;", " ,", _one_line(transaction.payee))
        out.append(f"{transaction.date.isoformat()} {payee}".rstrip())
        for note in transaction.notes:
            if _one_line(note):
                out.append(f"    ; {_one_line(note)}")
        width = max(len(p.account) for p in transaction.postings)
        for posting in transaction.postings:
            out.append(f"    {posting.account:<{width}}  {posting.amount:>12.2f}")
        out.append("")
    return "\n".join(out)
