import re
from datetime import date

from .model import AccountDecl, CommodityDecl, LedgerTransaction, PriceDecl
from .parse import _plain


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _symbol(code: str) -> str:
    """A commodity as ledger wants it written: plain letters as they are, anything else quoted."""
    return code if re.fullmatch(r"[A-Za-z_]+", code) else f'"{code}"'


def _example(decimals: int) -> str:
    return "1,000" + (f".{'0' * decimals}" if decimals else "")


def write(
    accounts: list[AccountDecl],
    transactions: list[LedgerTransaction],
    generated: date,
    commodities: list[CommodityDecl] | None = None,
    prices: list[PriceDecl] | None = None,
    labeled: bool = False,
) -> str:
    """Render a journal that ledger and hledger read as-is; amounts are debit positive.

    With `labeled`, every amount carries its commodity and conversions are written as
    `100 USD @@ 8350 INR`; without it the file has bare numbers, as for a single-currency ledger.
    """
    out = [f"; finode export, {generated.isoformat()}", ""]
    for commodity in commodities or []:
        line = f"commodity {_example(commodity.decimals or 0)} {_symbol(commodity.symbol)}"
        tags = [f"{key}:{_one_line(value).replace(',', ' ')}" for key, value in (("name", commodity.name), ("kind", commodity.kind)) if value]
        out.append(line + (f"  ; {', '.join(tags)}" if tags else ""))
    if commodities:
        out.append("")
    for decl in accounts:
        out.append(f"account {decl.name}")
        if decl.note:
            out.append(f"    note {_one_line(decl.note)}")
    if accounts:
        out.append("")
    for price in prices or []:
        quote = f" {_symbol(price.quote)}" if price.quote else ""
        out.append(f"P {price.date.isoformat()} {_symbol(price.symbol)} {_plain(price.price)}{quote}")
    if prices:
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
            if not labeled:
                out.append(f"    {posting.account:<{width}}  {posting.amount:>12.2f}")
                continue
            text = f"{_plain(posting.amount)} {_symbol(posting.commodity)}" if posting.commodity else _plain(posting.amount)
            if posting.cost is not None:
                text += f" @@ {_plain(posting.cost)} {_symbol(posting.cost_commodity)}"
            out.append(f"    {posting.account:<{width}}  {text:>16}")
        out.append("")
    return "\n".join(out)
