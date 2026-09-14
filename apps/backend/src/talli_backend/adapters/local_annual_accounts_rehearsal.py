"""Local file, clock, XML and credential seams for Annual Accounts rehearsal."""
from collections.abc import Mapping
from pathlib import Path

from talli_backend.authority_tools._filing import (
    _parse_json, git_commit, now, read_evidence, required, write_evidence,
)
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsRehearsalIO, annual_accounts_authority_adapter,
)


@annual_accounts_authority_adapter(AnnualAccountsRehearsalIO)
class LocalAnnualAccountsRehearsal:
    def __init__(self, environment, *, client_factory, generate, validate):
        self.environment = environment
        self.client_factory, self._generate, self._validate = client_factory, generate, validate

    def load_case(self):
        self.case_path = Path(required(self.environment, 'TALLI_ANNUAL_ACCOUNTS_CASE_PATH')).resolve()
        self.evidence_path = Path(required(self.environment, 'TALLI_ANNUAL_ACCOUNTS_EVIDENCE_PATH')).resolve()
        return _parse_json(self.case_path.read_text())

    def load_evidence(self):
        return read_evidence(self.evidence_path)

    def save_evidence(self, evidence):
        write_evidence(self.evidence_path, evidence)

    def case_filename(self):
        return self.case_path.name

    def evidence_filename(self):
        return self.evidence_path.name

    def revision(self):
        return git_commit()

    def timestamp(self):
        return now()

    async def connect(self, evidence):
        return await self.client_factory(self.environment, evidence)

    def generate(self, operation, values):
        return self._generate(operation, values)

    def validate_documents(self, documents):
        self._validate(documents)


def local_annual_accounts_summary(value):
    """Detach the immutable owned result into the original CLI JSON shape."""
    if isinstance(value, Mapping):
        return {key: local_annual_accounts_summary(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [local_annual_accounts_summary(item) for item in value]
    return value
