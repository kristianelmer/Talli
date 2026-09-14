"""Local file, clock, schema and credential seams for Company Tax rehearsal."""
from __future__ import annotations

from pathlib import Path

from talli_backend.authority_tools._filing import (
    _parse_json, check_private_key_file, git_commit, now, read_evidence, required, write_evidence,
)
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxRehearsalIO, company_tax_authority_adapter,
)


@company_tax_authority_adapter(CompanyTaxRehearsalIO)
class LocalCompanyTaxRehearsal:
    def __init__(self, environment, *, client_factory, generate, validate, real_client):
        self.environment = environment
        self.client_factory, self._generate, self._validate = client_factory, generate, validate
        self.real_client = real_client

    def select_evidence(self):
        self.evidence_path = Path(required(self.environment, "TALLI_COMPANY_TAX_EVIDENCE_PATH")).resolve()

    def load_evidence(self):
        return read_evidence(self.evidence_path)

    def load_case(self):
        self.case_path = Path(required(self.environment, "TALLI_COMPANY_TAX_CASE_PATH")).resolve()
        self.xsd = Path(required(self.environment, "TALLI_SKATTE_XSD_DIR")).resolve()
        return _parse_json(self.case_path.read_text())

    def save_evidence(self, evidence):
        write_evidence(self.evidence_path, evidence)

    def evidence_filename(self):
        return self.evidence_path.name

    def case_filename(self):
        return self.case_path.name

    def revision(self):
        return git_commit()

    def timestamp(self):
        return now()

    def prepare_credentials(self):
        if self.real_client:
            check_private_key_file(self.environment)

    async def connect(self, evidence):
        return await self.client_factory(self.environment, evidence)

    def generate(self, operation, values):
        return self._generate(operation, values)

    def validate_documents(self, documents, envelope, schemas):
        names = ("skattemelding.xml", "naeringsspesifikasjon.xml", "envelope.xml")
        self._validate(dict(zip(names, (documents["skattemeldingXml"], documents["naeringsspesifikasjonXml"], envelope))),
            dict(zip(names, (self.xsd / name for name in schemas))))
