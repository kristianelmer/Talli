from __future__ import annotations

import hashlib
from datetime import date

import pytest

from talli_backend.modules.banking.public import (
    BankAccountId,
    BankFileColumnMapping,
    BankFilePreviewCommand,
    BankSourceFileId,
    BankTransactionState,
    BankingError,
    SupportedBankDataFormat,
)
from talli_backend.modules.banking.service import BankingService
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
    IdempotencyKey,
    IncomeYear,
    LocalDate,
    UserId,
)


COMPANY_ID = CompanyId("10000000-0000-0000-0000-000000000001")
ACTOR_ID = ActorId(ActorKind.USER, UserId("20000000-0000-0000-0000-000000000002"))
ACCOUNT_ID = BankAccountId("30000000-0000-0000-0000-000000000003")


def command(data_format: SupportedBankDataFormat, content: str) -> BankFilePreviewCommand:
    return BankFilePreviewCommand(
        company_id=COMPANY_ID,
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("bank-file-preview"),
        idempotency_key=IdempotencyKey("40000000-0000-4000-8000-000000000004"),
        income_year=IncomeYear(2026),
        source_file_id=BankSourceFileId(
            "50000000-0000-0000-0000-000000000005"
        ),
        account_id=ACCOUNT_ID,
        data_format=data_format,
        filename="statement.csv" if data_format is SupportedBankDataFormat.CSV else "statement.xml",
        content=content,
        column_mapping=(
            BankFileColumnMapping(
                booking_date="date",
                value_date="value_date",
                text="text",
                amount="amount",
                balance="balance",
                reference="reference",
                state="status",
            )
            if data_format is SupportedBankDataFormat.CSV
            else None
        ),
    )


CSV = """date,value_date,text,amount,balance,reference,status
2026-01-02,2026-01-02,Årsgebyr,-89.00,1000.00,bank-ref-1,booked
"""


CAMT = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08">
  <BkToCstmrStmt><Stmt><Id>statement-1</Id>
    <Acct><Id><IBAN>NO12345678901</IBAN></Id><Ccy>NOK</Ccy></Acct>
    <Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt Ccy="NOK">1089.00</Amt></Bal>
    <Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="NOK">1000.00</Amt></Bal>
    <Ntry><Amt Ccy="NOK">89.00</Amt><CdtDbtInd>DBIT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts>
      <BookgDt><Dt>2026-01-02</Dt></BookgDt><ValDt><Dt>2026-01-02</Dt></ValDt>
      <NtryDtls><TxDtls><Refs><AcctSvcrRef>bank-ref-1</AcctSvcrRef></Refs>
        <RmtInf><Ustrd>Årsgebyr</Ustrd></RmtInf>
      </TxDtls></NtryDtls>
    </Ntry>
  </Stmt></BkToCstmrStmt>
</Document>
"""


def test_csv_and_camt_preview_normalize_to_the_same_stable_transaction_identity() -> None:
    csv_preview = BankingService.preview_file(command(SupportedBankDataFormat.CSV, CSV))
    camt_preview = BankingService.preview_file(command(SupportedBankDataFormat.CAMT053, CAMT))

    assert csv_preview.transaction_count == 1
    assert camt_preview.transaction_count == 1
    assert csv_preview.transactions[0].source_hash == camt_preview.transactions[0].source_hash
    assert camt_preview.account_mask == "•••• 8901"
    assert camt_preview.interval_start == LocalDate(date(2026, 1, 2))
    assert camt_preview.interval_end == LocalDate(date(2026, 1, 2))
    assert camt_preview.opening_balance is not None
    assert camt_preview.closing_balance is not None
    assert camt_preview.transactions[0].state is BankTransactionState.BOOKED


def test_preview_hashes_and_preserves_the_exact_original_file_evidence() -> None:
    preview = BankingService.preview_file(command(SupportedBankDataFormat.CAMT053, CAMT))

    assert preview.filename == "statement.xml"
    assert preview.document_sha256 == hashlib.sha256(CAMT.encode()).hexdigest()
    assert preview.currency == "NOK"


@pytest.mark.parametrize(
    "unsafe",
    [
        "<!DOCTYPE x [<!ENTITY y 'boom'>]><Document>&y;</Document>",
        CAMT.replace("NOK", "EUR"),
        CAMT.replace("2026-01-02", "2025-12-31"),
    ],
)
def test_camt_rejects_entities_currency_mismatch_and_out_of_year_rows(unsafe: str) -> None:
    with pytest.raises(BankingError) as failure:
        BankingService.preview_file(command(SupportedBankDataFormat.CAMT053, unsafe))

    assert failure.value.code == "BANKING_STATEMENT_INVALID"
