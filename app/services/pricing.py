"""Cart / invoice arithmetic (pure functions, Decimal only).

Per line:
    gross            = unit_price x quantity
    item discount    = fixed amount, or gross x percent / 100
    net              = gross - item discount
    bill share       = bill discount allocated pro-rata to ``net``
                       (the last line absorbs the rounding remainder)
    post-discount    = net - bill share
    Tax-exclusive price: taxable = post-discount; tax = taxable x rate / 100
    Tax-inclusive price: taxable = post-discount x 100 / (100 + rate);
                         tax = post-discount - taxable
    line total       = taxable + tax
Intra-state: CGST = tax / 2 (rounded), SGST = tax - CGST.
Inter-state: IGST = tax.
Grand total = sum of line totals (+ optional round-off to the nearest unit).

Every amount is rounded to 2 decimals (ROUND_HALF_UP) at line level so that
the stored lines always add up exactly to the stored totals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from app.config.constants import TaxMode
from app.services.errors import ValidationError
from app.utils.money import ZERO, money, qty

HUNDRED = Decimal(100)


@dataclass
class CartLineInput:
    product_id: int
    name: str
    unit_price: Decimal
    quantity: Decimal
    tax_rate: Decimal = ZERO
    price_includes_tax: bool = True
    discount_amount: Decimal = ZERO
    discount_percent: Decimal | None = None
    tax_rate_id: int | None = None
    tax_name: str = ""


@dataclass
class LineResult:
    gross: Decimal
    discount: Decimal
    net: Decimal
    bill_share: Decimal
    taxable: Decimal
    tax: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    total: Decimal


@dataclass
class CartResult:
    lines: list[LineResult] = field(default_factory=list)
    gross_total: Decimal = ZERO
    item_discount_total: Decimal = ZERO
    subtotal: Decimal = ZERO          # after item discounts, before bill discount
    bill_discount: Decimal = ZERO
    taxable_total: Decimal = ZERO
    cgst_total: Decimal = ZERO
    sgst_total: Decimal = ZERO
    igst_total: Decimal = ZERO
    tax_total: Decimal = ZERO
    round_off: Decimal = ZERO
    grand_total: Decimal = ZERO

    @property
    def total_discount(self) -> Decimal:
        return self.item_discount_total + self.bill_discount

    @property
    def discount_percent_of_gross(self) -> Decimal:
        if self.gross_total <= 0:
            return ZERO
        return (self.total_discount * HUNDRED / self.gross_total).quantize(Decimal("0.01"))


def _allocate(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Split ``total`` pro-rata over ``weights`` exactly (to the paisa),
    never allocating more than a line's weight."""
    base = sum(weights, ZERO)
    if total == 0 or base == 0:
        return [ZERO] * len(weights)
    shares = [money(total * w / base) for w in weights]
    diff = total - sum(shares, ZERO)
    step = Decimal("0.01") if diff > 0 else Decimal("-0.01")
    i = len(weights) - 1
    guard = 0
    while diff != 0 and guard < 100000:
        guard += 1
        cand = shares[i] + step
        if 0 <= cand <= weights[i]:
            shares[i] = cand
            diff -= step
        i = (i - 1) % len(weights)
    return shares


def compute_line_tax(post: Decimal, rate: Decimal, inclusive: bool,
                     tax_mode: str) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    if rate < 0 or rate > 100:
        raise ValidationError("Invalid tax rate.")
    if inclusive:
        taxable = money(post * HUNDRED / (HUNDRED + rate))
        tax = post - taxable
    else:
        taxable = post
        tax = money(taxable * rate / HUNDRED)
    if tax_mode == TaxMode.INTER:
        cgst = sgst = ZERO
        igst = tax
    else:
        cgst = money(tax / 2)
        sgst = tax - cgst
        igst = ZERO
    return taxable, tax, cgst, sgst, igst


def compute_cart(lines: list[CartLineInput], *, bill_discount_amount: Decimal = ZERO,
                 bill_discount_percent: Decimal | None = None, tax_mode: str = TaxMode.INTRA,
                 round_off: bool = False) -> CartResult:
    if tax_mode not in (TaxMode.INTRA, TaxMode.INTER):
        raise ValidationError("Invalid tax mode.")
    res = CartResult()
    nets: list[Decimal] = []
    partial: list[tuple[Decimal, Decimal, Decimal]] = []
    for ln in lines:
        q = qty(ln.quantity)
        if q <= 0:
            raise ValidationError(f"Quantity for “{ln.name}” must be greater than zero.")
        price = money(ln.unit_price)
        if price < 0:
            raise ValidationError(f"Price for “{ln.name}” cannot be negative.")
        gross = money(price * q)
        if ln.discount_percent is not None:
            pct = Decimal(ln.discount_percent)
            if pct < 0 or pct > 100:
                raise ValidationError("Discount percentage must be between 0 and 100.")
            disc = money(gross * pct / HUNDRED)
        else:
            disc = money(ln.discount_amount or ZERO)
        if disc < 0:
            raise ValidationError("Discount cannot be negative.")
        if disc > gross:
            raise ValidationError(f"Discount on “{ln.name}” exceeds the line amount.")
        net = gross - disc
        nets.append(net)
        partial.append((gross, disc, net))

    subtotal = sum(nets, ZERO)
    if bill_discount_percent is not None:
        pct = Decimal(bill_discount_percent)
        if pct < 0 or pct > 100:
            raise ValidationError("Bill discount percentage must be between 0 and 100.")
        bill = money(subtotal * pct / HUNDRED)
    else:
        bill = money(bill_discount_amount or ZERO)
    if bill < 0:
        raise ValidationError("Bill discount cannot be negative.")
    if bill > subtotal:
        raise ValidationError("Bill discount exceeds the bill amount.")
    shares = _allocate(bill, nets)

    for ln, (gross, disc, net), share in zip(lines, partial, shares):
        post = net - share
        taxable, tax, cgst, sgst, igst = compute_line_tax(
            post, Decimal(ln.tax_rate or 0), ln.price_includes_tax, tax_mode)
        lr = LineResult(gross=gross, discount=disc, net=net, bill_share=share, taxable=taxable,
                        tax=tax, cgst=cgst, sgst=sgst, igst=igst, total=taxable + tax)
        res.lines.append(lr)
        res.gross_total += gross
        res.item_discount_total += disc
        res.taxable_total += taxable
        res.cgst_total += cgst
        res.sgst_total += sgst
        res.igst_total += igst
        res.tax_total += tax
    res.subtotal = subtotal
    res.bill_discount = bill
    lines_total = res.taxable_total + res.tax_total
    if round_off:
        rounded = lines_total.quantize(Decimal(1), rounding=ROUND_HALF_UP)
        res.round_off = rounded - lines_total
        res.grand_total = rounded
    else:
        res.grand_total = lines_total
    return res
