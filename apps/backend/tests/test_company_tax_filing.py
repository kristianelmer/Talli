"""Permanent frozen-input characterization of supported settlement preview policy."""
import json
from pathlib import Path

import pytest

from talli_backend.modules.company_tax_filing.public import (
    TaxSettlementInput, TaxSettlementValidationError, normalize_tax_settlement,
)
from talli_backend.modules.ledger.public import TaxSettlementKind, preview_tax_settlement_lines
from talli_backend.shared.kernel import Money

CASES = json.loads((Path(__file__).parents[3] / 'architecture/evidence/issues/146/legacy-preview-cases.json').read_text())['cases']


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['name'])
def test_frozen_settlement_preview(case):
    value = case['input']
    command = TaxSettlementInput(value['settlementDate'], value['amount'], value['settlementType'], value['documentStatus'], value.get('bankTransactionId'), value.get('documentId'))
    try:
        normalized = normalize_tax_settlement(command)
    except TaxSettlementValidationError as error:
        assert {'name': 'TaxSettlementValidationError', 'code': error.code, 'message': error.message} == case['error']
        return
    lines = preview_tax_settlement_lines(TaxSettlementKind(normalized.settlement_kind), Money.nok(str(normalized.amount)))
    assert {
        'payload': {'settlement_date': normalized.settlement_date, 'amount': normalized.amount,
                    'settlement_type': normalized.settlement_kind, 'document_status': normalized.document_status,
                    'bank_transaction_id': normalized.bank_transaction_id, 'document_id': normalized.document_id},
        'lines': [{'account': line.account, 'description': line.description, 'debit': float(line.debit.amount), 'credit': float(line.credit.amount)} for line in lines],
        'expectedBankAmount': normalized.expected_bank_amount,
    } == case['result']
