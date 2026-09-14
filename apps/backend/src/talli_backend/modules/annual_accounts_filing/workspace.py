"""Validation of owned filing projections before they cross the public boundary."""
from collections.abc import Mapping
from uuid import UUID

from .public import AnnualAccountsError, AnnualAccountsFilingRows


def validate_rows(value: AnnualAccountsFilingRows) -> None:
    try:
        previews = {str(row['id']): row for row in value.previews}
        evidence = {str(row['id']): row for row in value.test_evidence}
        for name in ('previews', 'submissions', 'overrides', 'review_comments', 'permissions', 'test_evidence'):
            rows = getattr(value, name)
            ids = set()
            for row in rows:
                if not isinstance(row, Mapping) or str(UUID(str(row['id']))) != row['id']:
                    raise ValueError()
                if row['id'] in ids or row['company_id'] != str(value.company_id):
                    raise ValueError()
                ids.add(row['id'])
                if name in ('permissions', 'test_evidence'):
                    if row['obligation'] != 'aarsregnskap':
                        raise ValueError()
                elif name == 'review_comments':
                    if row['preview_id'] not in previews:
                        raise ValueError()
                else:
                    if (row['filing'] != 'årsregnskap'
                            or type(row['income_year']) is not int or not 2000 <= row['income_year'] <= 2100):
                        raise ValueError()
                    if value.income_year is not None and row['income_year'] != int(value.income_year):
                        raise ValueError()
                    if row.get('preview_id') is not None:
                        preview = previews[row['preview_id']]
                        if preview['income_year'] != row['income_year']:
                            raise ValueError()
                if name == 'submissions' and row.get('authority_test_run_id') is not None:
                    if row['authority_test_run_id'] not in evidence:
                        raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise AnnualAccountsError.unavailable() from None
