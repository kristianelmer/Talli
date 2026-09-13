"""The owned row boundary rejects cross-scope or incomplete repository results."""
import copy
import json
from pathlib import Path

import pytest

from talli_backend.modules.company_tax_filing.public import CompanyTaxError, CompanyTaxFilingRows
from talli_backend.shared.kernel import CompanyId, IncomeYear

FIXTURE = json.loads((Path(__file__).resolve().parents[3] / 'architecture/evidence/issues/152/legacy-database-characterization.json').read_text())
COMPANY = CompanyId('00000000-0000-0000-0000-000000000152')


def rows():
    return {'previews': [], 'submissions': copy.deepcopy(FIXTURE['persistedRows']['filing_submissions']),
            'overrides': [], 'review_comments': [], 'permissions': [],
            'test_evidence': copy.deepcopy(FIXTURE['persistedRows']['authority_test_runs'])}


def test_full_imported_source_rows_are_recursively_immutable():
    value = rows()
    snapshot = CompanyTaxFilingRows(COMPANY, IncomeYear(2025), **value)
    before = snapshot.submissions[0]['receipt_metadata']['contentSha256']
    value['submissions'][0]['receipt_metadata']['contentSha256'] = 'changed'
    assert snapshot.submissions[0]['receipt_metadata']['contentSha256'] == before
    with pytest.raises(TypeError):
        snapshot.submissions[0]['receipt_metadata']['contentSha256'] = 'changed'


@pytest.mark.parametrize('mutate', [
    lambda r: r['submissions'][0].update(company_id='00000000-0000-0000-0000-000000000199'),
    lambda r: r['submissions'][0].update(income_year=2024),
    lambda r: r['submissions'][0].update(filing='årsregnskap'),
    lambda r: r['submissions'].append(copy.deepcopy(r['submissions'][0])),
    lambda r: r['test_evidence'].clear(),
    lambda r: r['test_evidence'][0].update(obligation='aarsregnskap'),
    lambda r: r.update(submissions=None),
    lambda r: r.update(submissions={}),
    lambda r: r.update(submissions=''),
    lambda r: r['submissions'][0].update(id='not-an-id'),
])
def test_repository_scope_corruption_fails_closed(mutate):
    value = rows()
    mutate(value)
    with pytest.raises(CompanyTaxError) as error:
        CompanyTaxFilingRows(COMPANY, IncomeYear(2025), **value)
    assert error.value.code == 'COMPANY_TAX_DEPENDENCY_UNAVAILABLE'
