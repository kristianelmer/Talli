"""Pinned document-pair evidence, separate from runtime filing admission."""
from dataclasses import dataclass
import hashlib
import json
import re


@dataclass(frozen=True,slots=True)
class AnnualAccountsDocumentsInspection:
    schema_sha256: str
    organization_number: str
    income_year: int
    main_form_sha256: str
    company_accounts_sha256: str

    def __post_init__(self):
        if (type(self.organization_number) is not str or re.fullmatch('[0-9]{9}',self.organization_number) is None
                or type(self.income_year) is not int or self.income_year!=2025
                or any(type(value) is not str or re.fullmatch('[0-9a-f]{64}',value) is None for value in
                    (self.schema_sha256,self.main_form_sha256,self.company_accounts_sha256))):
            raise ValueError('Annual Accounts document inspection scope is invalid.')

    @property
    def canonical_json(self):
        return json.dumps({'version':'annual-accounts-document-inspection-v1','schemaSha256':self.schema_sha256,
            'organizationNumber':self.organization_number,'incomeYear':self.income_year,
            'mainFormSha256':self.main_form_sha256,'companyAccountsSha256':self.company_accounts_sha256},
            sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)

    @property
    def sha256(self):return hashlib.sha256(self.canonical_json.encode('utf-8')).hexdigest()
