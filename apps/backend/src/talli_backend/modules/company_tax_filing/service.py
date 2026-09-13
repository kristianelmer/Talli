"""Settlement normalization; account selection belongs to Ledger."""
from __future__ import annotations

import math
import re

from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,
    RecordTaxSettlementCommand,
    NormalizedTaxSettlement,
    TaxSettlementDocumentStatus,
    TaxSettlementInput,
    TaxSettlementKind,
    TaxSettlementValidationError,
)


def normalize(value: TaxSettlementInput) -> NormalizedTaxSettlement:
    settlement_date = value.settlement_date.strip("\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff")
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", settlement_date) is None:
        raise TaxSettlementValidationError("Oppgjørsdato må være YYYY-MM-DD.", "invalid_date")
    if isinstance(value.amount, bool) or not isinstance(value.amount, (int, float)) or not math.isfinite(value.amount) or value.amount <= 0:
        raise TaxSettlementValidationError("Skattebeløp må være større enn 0.", "invalid_amount")
    try:
        kind = TaxSettlementKind(value.settlement_kind)
    except ValueError:
        raise TaxSettlementValidationError("Ugyldig skatteoppgjørstype.", "invalid_settlement_type") from None
    try:
        status = TaxSettlementDocumentStatus(value.document_status)
    except ValueError:
        raise TaxSettlementValidationError("Ugyldig dokumentstatus.", "invalid_document_status") from None
    if kind is TaxSettlementKind.PAYABLE and value.bank_transaction_id:
        raise TaxSettlementValidationError(
            "Betalbar skatt-estimat skal ikke knyttes direkte til bank.", "payable_bank_link_blocked"
        )
    # Preserve the released binary64 multiplication and Math.round tie direction.
    # Comparing the fraction avoids adding .5 rounding a value just below a tie up.
    scaled = float(value.amount) * 100
    if not math.isfinite(scaled):
        raise TaxSettlementValidationError("Skattebeløp må være større enn 0.", "invalid_amount")
    integral = math.floor(scaled)
    amount = float(integral + (scaled - integral >= 0.5)) / 100
    return NormalizedTaxSettlement(
        settlement_date=settlement_date,
        amount=amount,
        settlement_kind=kind,
        document_status=status,
        bank_transaction_id=value.bank_transaction_id or None,
        document_id=value.document_id or None,
        expected_bank_amount=(-amount if kind is TaxSettlementKind.PAYMENT
                              else amount if kind is TaxSettlementKind.REFUND else None),
    )


def validate_new(command: RecordTaxSettlementCommand) -> None:
    if (
        command.amount.amount <= 0
        or command.settlement_date.value.year != int(command.income_year)
        or not isinstance(command.settlement_kind, TaxSettlementKind)
        or not isinstance(command.document_status, TaxSettlementDocumentStatus)
        or (command.settlement_kind is TaxSettlementKind.PAYABLE
            and command.bank_transaction_id is not None)
    ):
        raise CompanyTaxError.invalid_input()
