from __future__ import annotations

import csv
import json
import uuid
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from urllib.request import urlopen

from pydantic import BaseModel, ConfigDict, Field, model_validator

from holding_core.annual import (
    AnnualData,
    CompanyArchive,
    DocumentRecord,
    FilingSimulation,
    YearEndInterviewAnswers,
    assess_annual_accounts_readiness,
    assess_tax_return_readiness,
    build_annual_data,
    build_company_archive,
    simulate_annual_accounts,
    simulate_tax_return,
)
from holding_core.billing import CompanyBillingAccount, assign_founder_pricing, assign_standard_pricing, production_filing_gate
from holding_core.holding_actions import (
    AdminCostInput,
    DividendReceivedInput,
    DividendToOwnerInput,
    InvestmentPosition,
    SharePurchaseInput,
    ShareSaleInput,
    ShareholderLoanInput,
    TaxTreatment,
    build_admin_cost_entry,
    build_dividend_received,
    build_dividend_to_owner,
    build_share_purchase,
    build_share_sale,
    build_shareholder_loan,
)
from holding_core.ledger import DraftEntry, NarrowLedger, PostedEntry


class WorkspaceRole(StrEnum):
    OWNER = "owner"
    REVIEWER = "reviewer"
    READ_ONLY = "read_only"


class SupportStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    WARNING = "warning"


class FilingStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    WARNING = "warning"
    BLOCKED = "blocked"
    FILED = "filed"
    OVERDUE = "overdue"


class AuditCategory(StrEnum):
    COMPANY = "company"
    ACCESS = "access"
    DOCUMENT = "document"
    BANK = "bank"
    LEDGER = "ledger"
    ACTION = "action"
    REVIEW = "review"
    FILING = "filing"
    BILLING = "billing"


class Actor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    email: str
    name: str


class CompanyMembership(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: str
    company_id: str
    role: WorkspaceRole
    invited_by: str | None = None
    accepted_at: datetime | None = None


class SupportBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SupportStatus
    code: str
    message: str
    next_action: str


class CompanyIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_number: str = Field(pattern=r"^\d{9}$")
    name: str
    entity_type: str
    address: str = ""
    postal_code: str = ""
    city: str = ""
    status_text: str = ""
    source: str = "manual"
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    locked_at: datetime | None = None

    @property
    def is_locked(self) -> bool:
        return self.locked_at is not None


class AuditLogEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    company_id: str
    actor_id: str
    category: AuditCategory
    action: str
    message: str
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StoredDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    company_id: str
    income_year: int
    document_type: str
    name: str
    linked_to: str
    status: str = "attached"
    retention_years: int = 5
    storage_key: str
    created_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SignedDocumentUrl(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    url: str
    expires_at: datetime


class BankTransaction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    company_id: str
    income_year: int
    transaction_date: date
    text: str
    amount: float
    balance: float | None = None
    source_hash: str
    matched_entry_id: str | None = None
    matched_action_id: str | None = None
    accepted_warning: bool = False

    @property
    def is_matched(self) -> bool:
        return self.matched_entry_id is not None or self.matched_action_id is not None or self.accepted_warning


class StructuredAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    company_id: str
    income_year: int
    action_type: str
    status: Literal["draft", "posted", "blocked"] = "draft"
    payload: dict[str, Any]
    document_ids: tuple[str, ...] = ()
    bank_transaction_ids: tuple[str, ...] = ()
    ledger_entry_id: str | None = None
    support_boundary: SupportBoundary | None = None
    created_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ManualJournalRisk(StrEnum):
    NORMAL = "normal"
    WARNING = "warning"
    BLOCK = "block"


class ManualJournalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry: PostedEntry
    risk: ManualJournalRisk
    message: str


class InvestmentMovement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    movement_type: Literal["purchase", "sale", "dividend"]
    movement_date: date
    share_delta: float = 0
    cost_basis_delta: float = 0
    amount: float = 0


class InvestmentRegisterPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    company_id: str
    name: str
    tax_treatment: TaxTreatment
    org_number: str | None = None
    share_count: float = 0
    cost_basis: float = 0
    movements: tuple[InvestmentMovement, ...] = ()


class PeriodLock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: str
    income_year: int
    locked_by: str
    locked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str


class FilingOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    company_id: str
    income_year: int
    filing: str
    field_target: str
    old_value: str
    new_value: str
    reason: str = Field(min_length=5)
    risk_level: Literal["warning", "escalation", "block"]
    actor_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewComment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    company_id: str
    target: str
    body: str
    severity: Literal["advisory", "hard_block"] = "advisory"
    author_id: str
    acknowledged_by_owner: bool = False


class DeadlineState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filing: str
    deadline: date
    status: FilingStatus
    message: str


class FilingDashboardItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filing: str
    status: FilingStatus
    issues: tuple[str, ...]
    preview: str | None = None


class WorkspaceDashboard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: CompanyIdentity
    support_boundary: SupportBoundary
    filings: tuple[FilingDashboardItem, ...]
    deadlines: tuple[DeadlineState, ...]
    document_count: int
    unreconciled_bank_transactions: int
    archive_ready: bool


class CompanyWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: CompanyIdentity
    support_boundary: SupportBoundary
    memberships: tuple[CompanyMembership, ...]
    documents: tuple[StoredDocument, ...] = ()
    bank_transactions: tuple[BankTransaction, ...] = ()
    posted_entries: tuple[PostedEntry, ...] = ()
    structured_actions: tuple[StructuredAction, ...] = ()
    investment_positions: tuple[InvestmentRegisterPosition, ...] = ()
    period_locks: tuple[PeriodLock, ...] = ()
    filing_overrides: tuple[FilingOverride, ...] = ()
    review_comments: tuple[ReviewComment, ...] = ()
    billing_account: CompanyBillingAccount | None = None
    audit_events: tuple[AuditLogEvent, ...] = ()


class WorkspaceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actors: tuple[Actor, ...] = ()
    workspaces: tuple[CompanyWorkspace, ...] = ()


class WorkspaceStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.snapshot = self._load()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def upsert_actor(self, actor: Actor) -> Actor:
        actors = [item for item in self.snapshot.actors if item.id != actor.id] + [actor]
        self.snapshot = self.snapshot.model_copy(update={"actors": tuple(actors)})
        self.save()
        return actor

    def create_workspace(self, actor_id: str, identity: CompanyIdentity) -> CompanyWorkspace:
        if identity.org_number in {workspace.company.org_number for workspace in self.snapshot.workspaces}:
            raise ValueError("company workspace already exists")
        support = support_boundary_for_identity(identity)
        membership = CompanyMembership(
            actor_id=actor_id,
            company_id=identity.org_number,
            role=WorkspaceRole.OWNER,
            accepted_at=datetime.now(UTC),
        )
        workspace = CompanyWorkspace(
            company=identity,
            support_boundary=support,
            memberships=(membership,),
            billing_account=assign_standard_pricing(identity.org_number),
            audit_events=(
                _audit(identity.org_number, actor_id, AuditCategory.COMPANY, "workspace_created", "Selskapsarbeidsflate opprettet."),
            ),
        )
        self.snapshot = self.snapshot.model_copy(update={"workspaces": self.snapshot.workspaces + (workspace,)})
        self.save()
        return workspace

    def get_workspace(self, actor_id: str, company_id: str, *, roles: tuple[WorkspaceRole, ...] | None = None) -> CompanyWorkspace:
        workspace = self._workspace(company_id)
        membership = _membership(workspace, actor_id)
        if roles is not None and membership.role not in roles:
            raise PermissionError("actor does not have required company role")
        return workspace

    def replace_workspace(self, workspace: CompanyWorkspace) -> CompanyWorkspace:
        workspaces = [item for item in self.snapshot.workspaces if item.company.org_number != workspace.company.org_number]
        self.snapshot = self.snapshot.model_copy(update={"workspaces": tuple(workspaces) + (workspace,)})
        self.save()
        return workspace

    def _workspace(self, company_id: str) -> CompanyWorkspace:
        for workspace in self.snapshot.workspaces:
            if workspace.company.org_number == company_id:
                return workspace
        raise ValueError("company workspace not found")

    def _load(self) -> WorkspaceSnapshot:
        if not self.path.exists():
            return WorkspaceSnapshot()
        return WorkspaceSnapshot.model_validate_json(self.path.read_text(encoding="utf-8"))


def support_boundary_for_identity(identity: CompanyIdentity) -> SupportBoundary:
    if identity.entity_type != "AS":
        return SupportBoundary(
            status=SupportStatus.BLOCKED,
            code="unsupported_entity_type",
            message="Talli støtter kun AS i første versjon.",
            next_action="Bruk et annet system eller kontakt regnskapsfører.",
        )
    return SupportBoundary(
        status=SupportStatus.READY,
        code="simple_holding_as",
        message="Selskapet passer enkel holding AS-løypen.",
        next_action="Bekreft selskapsidentitet og innsendingsrett.",
    )


def map_brreg_entity(payload: dict[str, Any]) -> CompanyIdentity:
    address = payload.get("forretningsadresse") or payload.get("postadresse") or {}
    entity_form = payload.get("organisasjonsform") or {}
    return CompanyIdentity(
        org_number=str(payload["organisasjonsnummer"]),
        name=payload["navn"],
        entity_type=entity_form.get("kode", ""),
        address=", ".join(address.get("adresse", []) or []),
        postal_code=address.get("postnummer", "") or "",
        city=address.get("poststed", "") or "",
        status_text="under avvikling" if payload.get("underAvvikling") else "aktiv",
        source="brreg",
    )


def fetch_brreg_identity(org_number: str, *, fetcher: Any | None = None) -> CompanyIdentity:
    if not org_number.isdigit() or len(org_number) != 9:
        raise ValueError("organization number must have 9 digits")
    url = f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}"
    if fetcher is None:
        with urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    else:
        payload = fetcher(url)
    return map_brreg_entity(payload)


def confirm_company_identity(store: WorkspaceStore, actor_id: str, company_id: str) -> CompanyWorkspace:
    workspace = store.get_workspace(actor_id, company_id, roles=(WorkspaceRole.OWNER,))
    identity = workspace.company.model_copy(
        update={"confirmed_by": actor_id, "confirmed_at": datetime.now(UTC), "locked_at": datetime.now(UTC)}
    )
    workspace = _with_audit(
        workspace.model_copy(update={"company": identity}),
        actor_id,
        AuditCategory.COMPANY,
        "identity_confirmed",
        "Selskapsidentitet bekreftet og låst for filing.",
    )
    return store.replace_workspace(workspace)


def invite_member(
    store: WorkspaceStore,
    actor_id: str,
    company_id: str,
    *,
    invited_actor_id: str,
    role: WorkspaceRole,
) -> CompanyWorkspace:
    workspace = store.get_workspace(actor_id, company_id, roles=(WorkspaceRole.OWNER,))
    if role == WorkspaceRole.OWNER:
        raise ValueError("owner role cannot be delegated by invite workflow")
    membership = CompanyMembership(
        actor_id=invited_actor_id,
        company_id=company_id,
        role=role,
        invited_by=actor_id,
        accepted_at=datetime.now(UTC),
    )
    memberships = tuple(item for item in workspace.memberships if item.actor_id != invited_actor_id) + (membership,)
    workspace = _with_audit(
        workspace.model_copy(update={"memberships": memberships}),
        actor_id,
        AuditCategory.ACCESS,
        "member_invited",
        f"Tilgang gitt til {invited_actor_id} som {role.value}.",
    )
    return store.replace_workspace(workspace)


def add_review_comment(
    store: WorkspaceStore,
    actor_id: str,
    company_id: str,
    *,
    target: str,
    body: str,
    severity: Literal["advisory", "hard_block"] = "advisory",
) -> CompanyWorkspace:
    workspace = store.get_workspace(actor_id, company_id, roles=(WorkspaceRole.OWNER, WorkspaceRole.REVIEWER))
    comment = ReviewComment(company_id=company_id, target=target, body=body, severity=severity, author_id=actor_id)
    workspace = _with_audit(
        workspace.model_copy(update={"review_comments": workspace.review_comments + (comment,)}),
        actor_id,
        AuditCategory.REVIEW,
        "review_comment_added",
        f"Review-kommentar lagt til på {target}.",
    )
    return store.replace_workspace(workspace)


def acknowledge_review_comment(store: WorkspaceStore, actor_id: str, company_id: str, comment_id: str) -> CompanyWorkspace:
    workspace = store.get_workspace(actor_id, company_id, roles=(WorkspaceRole.OWNER,))
    comments: list[ReviewComment] = []
    found = False
    for comment in workspace.review_comments:
        if comment.id != comment_id:
            comments.append(comment)
            continue
        found = True
        if comment.severity == "hard_block":
            raise ValueError("Hard systemblokk kan ikke overstyres av eier.")
        comments.append(comment.model_copy(update={"acknowledged_by_owner": True}))
    if not found:
        raise ValueError("review comment not found")
    workspace = _with_audit(
        workspace.model_copy(update={"review_comments": tuple(comments)}),
        actor_id,
        AuditCategory.REVIEW,
        "review_comment_acknowledged",
        "Review-kommentar akseptert av eier.",
    )
    return store.replace_workspace(workspace)


def attach_document(
    store: WorkspaceStore,
    actor_id: str,
    company_id: str,
    *,
    income_year: int,
    document_type: str,
    name: str,
    linked_to: str,
    storage_key: str,
    status: str = "attached",
) -> CompanyWorkspace:
    workspace = store.get_workspace(actor_id, company_id, roles=(WorkspaceRole.OWNER,))
    document = StoredDocument(
        company_id=company_id,
        income_year=income_year,
        document_type=document_type,
        name=name,
        linked_to=linked_to,
        storage_key=storage_key,
        status=status,
        created_by=actor_id,
    )
    workspace = _with_audit(
        workspace.model_copy(update={"documents": workspace.documents + (document,)}),
        actor_id,
        AuditCategory.DOCUMENT,
        "document_attached",
        f"Dokument lagt til: {name}.",
    )
    return store.replace_workspace(workspace)


def create_signed_document_url(
    store: WorkspaceStore,
    actor_id: str,
    company_id: str,
    document_id: str,
    *,
    expires_in_seconds: int = 300,
) -> SignedDocumentUrl:
    workspace = store.get_workspace(actor_id, company_id)
    document = next((item for item in workspace.documents if item.id == document_id), None)
    if document is None:
        raise ValueError("document not found")
    expires_at = datetime.fromtimestamp(datetime.now(UTC).timestamp() + expires_in_seconds, UTC)
    token = uuid.uuid5(uuid.NAMESPACE_URL, f"{document.storage_key}:{actor_id}:{expires_at.isoformat()}")
    return SignedDocumentUrl(document_id=document.id, url=f"talli-signed://{document.storage_key}?token={token}", expires_at=expires_at)


def import_bank_csv(
    store: WorkspaceStore,
    actor_id: str,
    company_id: str,
    *,
    income_year: int,
    csv_text: str,
) -> CompanyWorkspace:
    workspace = store.get_workspace(actor_id, company_id, roles=(WorkspaceRole.OWNER,))
    rows = list(csv.DictReader(csv_text.splitlines()))
    required = {"date", "text", "amount"}
    if rows and not required.issubset(rows[0].keys()):
        raise ValueError("bank CSV requires date,text,amount columns")
    transactions = list(workspace.bank_transactions)
    seen = {item.source_hash for item in transactions}
    for row in rows:
        source_hash = _stable_id(row.get("date", ""), row.get("text", ""), row.get("amount", ""), row.get("balance", ""))
        if source_hash in seen:
            continue
        seen.add(source_hash)
        transactions.append(
            BankTransaction(
                company_id=company_id,
                income_year=income_year,
                transaction_date=date.fromisoformat(row["date"]),
                text=row["text"],
                amount=float(row["amount"]),
                balance=float(row["balance"]) if row.get("balance") else None,
                source_hash=source_hash,
            )
        )
    workspace = _with_audit(
        workspace.model_copy(update={"bank_transactions": tuple(transactions)}),
        actor_id,
        AuditCategory.BANK,
        "bank_csv_imported",
        f"Importerte {len(transactions) - len(workspace.bank_transactions)} banktransaksjoner.",
    )
    return store.replace_workspace(workspace)


def match_bank_transaction(
    store: WorkspaceStore,
    actor_id: str,
    company_id: str,
    transaction_id: str,
    *,
    entry_id: str | None = None,
    action_id: str | None = None,
    accepted_warning: bool = False,
) -> CompanyWorkspace:
    workspace = store.get_workspace(actor_id, company_id, roles=(WorkspaceRole.OWNER,))
    updated: list[BankTransaction] = []
    found = False
    for transaction in workspace.bank_transactions:
        if transaction.id != transaction_id:
            updated.append(transaction)
            continue
        found = True
        updated.append(
            transaction.model_copy(
                update={
                    "matched_entry_id": entry_id,
                    "matched_action_id": action_id,
                    "accepted_warning": accepted_warning,
                }
            )
        )
    if not found:
        raise ValueError("bank transaction not found")
    workspace = _with_audit(
        workspace.model_copy(update={"bank_transactions": tuple(updated)}),
        actor_id,
        AuditCategory.BANK,
        "bank_transaction_matched",
        "Banktransaksjon avstemt.",
    )
    return store.replace_workspace(workspace)


def record_holding_action(
    store: WorkspaceStore,
    actor_id: str,
    company_id: str,
    *,
    income_year: int,
    action_input: (
        AdminCostInput
        | DividendReceivedInput
        | SharePurchaseInput
        | ShareSaleInput
        | DividendToOwnerInput
        | ShareholderLoanInput
    ),
    document_ids: tuple[str, ...] = (),
    bank_transaction_ids: tuple[str, ...] = (),
    post: bool = True,
) -> CompanyWorkspace:
    workspace = store.get_workspace(actor_id, company_id, roles=(WorkspaceRole.OWNER,))
    _assert_not_locked(workspace, income_year)
    result = _build_action_entry(action_input)
    entry = result["entry"]
    ledger = NarrowLedger()
    for posted in workspace.posted_entries:
        ledger._posted[posted.id] = posted
    ledger.create_draft(entry)
    posted_entry = ledger.post(entry.id) if post else None
    action = StructuredAction(
        company_id=company_id,
        income_year=income_year,
        action_type=result["action_type"],
        status="posted" if posted_entry else "draft",
        payload=action_input.model_dump(mode="json"),
        document_ids=document_ids,
        bank_transaction_ids=bank_transaction_ids,
        ledger_entry_id=posted_entry.id if posted_entry else entry.id,
        created_by=actor_id,
    )
    workspace = workspace.model_copy(
        update={
            "structured_actions": workspace.structured_actions + (action,),
            "posted_entries": workspace.posted_entries + ((posted_entry,) if posted_entry else ()),
        }
    )
    workspace = _apply_investment_result(workspace, result, action)
    workspace = _with_audit(workspace, actor_id, AuditCategory.ACTION, "holding_action_recorded", f"Handling lagret: {action.action_type}.")
    return store.replace_workspace(workspace)


def record_manual_journal(
    store: WorkspaceStore,
    actor_id: str,
    company_id: str,
    *,
    income_year: int,
    entry: DraftEntry,
    explanation: str,
    accept_warning: bool = False,
) -> tuple[CompanyWorkspace, ManualJournalResult]:
    workspace = store.get_workspace(actor_id, company_id, roles=(WorkspaceRole.OWNER,))
    _assert_not_locked(workspace, income_year)
    risk = _manual_journal_risk(entry)
    if risk == ManualJournalRisk.BLOCK:
        raise ValueError("manual journal touches blocked filing-sensitive accounts")
    if risk == ManualJournalRisk.WARNING and not accept_warning:
        raise ValueError("manual journal touches filing-sensitive accounts and requires warning acceptance")
    ledger = NarrowLedger()
    ledger.create_draft(entry)
    posted = ledger.post(entry.id)
    action = StructuredAction(
        company_id=company_id,
        income_year=income_year,
        action_type="manual_journal",
        status="posted",
        payload={"memo": entry.memo, "explanation": explanation, "risk": risk.value},
        ledger_entry_id=posted.id,
        created_by=actor_id,
        support_boundary=SupportBoundary(
            status=SupportStatus.WARNING if risk == ManualJournalRisk.WARNING else SupportStatus.READY,
            code=f"manual_journal_{risk.value}",
            message="Manuell postering er registrert med filingrisiko." if risk == ManualJournalRisk.WARNING else "Manuell postering registrert.",
            next_action="Kontroller filingstatus før innsending.",
        ),
    )
    workspace = _with_audit(
        workspace.model_copy(
            update={
                "posted_entries": workspace.posted_entries + (posted,),
                "structured_actions": workspace.structured_actions + (action,),
            }
        ),
        actor_id,
        AuditCategory.LEDGER,
        "manual_journal_posted",
        f"Manuell postering lagret: {explanation}.",
    )
    workspace = store.replace_workspace(workspace)
    return workspace, ManualJournalResult(
        entry=posted,
        risk=risk,
        message="Manuell postering krever filingkontroll." if risk == ManualJournalRisk.WARNING else "Manuell postering lagret.",
    )


def lock_period(store: WorkspaceStore, actor_id: str, company_id: str, *, income_year: int, reason: str) -> CompanyWorkspace:
    workspace = store.get_workspace(actor_id, company_id, roles=(WorkspaceRole.OWNER,))
    lock = PeriodLock(company_id=company_id, income_year=income_year, locked_by=actor_id, reason=reason)
    workspace = _with_audit(
        workspace.model_copy(update={"period_locks": workspace.period_locks + (lock,)}),
        actor_id,
        AuditCategory.FILING,
        "period_locked",
        f"År {income_year} låst: {reason}.",
    )
    return store.replace_workspace(workspace)


def add_filing_override(
    store: WorkspaceStore,
    actor_id: str,
    company_id: str,
    *,
    income_year: int,
    filing: str,
    field_target: str,
    old_value: str,
    new_value: str,
    reason: str,
    risk_level: Literal["warning", "escalation", "block"],
) -> CompanyWorkspace:
    workspace = store.get_workspace(actor_id, company_id, roles=(WorkspaceRole.OWNER,))
    override = FilingOverride(
        company_id=company_id,
        income_year=income_year,
        filing=filing,
        field_target=field_target,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        risk_level=risk_level,
        actor_id=actor_id,
    )
    workspace = _with_audit(
        workspace.model_copy(update={"filing_overrides": workspace.filing_overrides + (override,)}),
        actor_id,
        AuditCategory.FILING,
        "filing_override_added",
        f"Manuell filing-overstyring lagt til for {field_target}.",
    )
    return store.replace_workspace(workspace)


def generate_owner_dividend_documents(store: WorkspaceStore, actor_id: str, company_id: str, action_id: str) -> CompanyWorkspace:
    workspace = store.get_workspace(actor_id, company_id, roles=(WorkspaceRole.OWNER,))
    action = next((item for item in workspace.structured_actions if item.id == action_id), None)
    if action is None or action.action_type != "dividend_to_owner":
        raise ValueError("owner dividend action not found")
    names = ("Styreforslag utbytte.txt", "Generalforsamlingsprotokoll utbytte.txt")
    documents = tuple(
        StoredDocument(
            company_id=company_id,
            income_year=action.income_year,
            document_type="corporate_document",
            name=name,
            linked_to=action.id,
            storage_key=f"generated/{company_id}/{action.income_year}/{action.id}/{name}",
            created_by=actor_id,
        )
        for name in names
    )
    workspace = _with_audit(
        workspace.model_copy(update={"documents": workspace.documents + documents}),
        actor_id,
        AuditCategory.DOCUMENT,
        "corporate_documents_generated",
        "Styreforslag og generalforsamlingsprotokoll generert.",
    )
    return store.replace_workspace(workspace)


def record_tax_settlement(
    store: WorkspaceStore,
    actor_id: str,
    company_id: str,
    *,
    income_year: int,
    amount: float,
    settlement_type: Literal["payable", "refund", "payment", "prior_year_difference"],
) -> CompanyWorkspace:
    workspace = store.get_workspace(actor_id, company_id, roles=(WorkspaceRole.OWNER,))
    _assert_not_locked(workspace, income_year)
    if amount <= 0:
        raise ValueError("tax settlement amount must be positive")
    if settlement_type in {"payable", "prior_year_difference"}:
        lines = [
            {"account": "8300", "description": "Skattekostnad", "debit": amount, "credit": 0},
            {"account": "2500", "description": "Betalbar skatt", "debit": 0, "credit": amount},
        ]
    elif settlement_type == "refund":
        lines = [
            {"account": "1570", "description": "Skatt til gode", "debit": amount, "credit": 0},
            {"account": "8300", "description": "Skattekostnad reduksjon", "debit": 0, "credit": amount},
        ]
    else:
        lines = [
            {"account": "2500", "description": "Betalt skatt", "debit": amount, "credit": 0},
            {"account": "1920", "description": "Bank", "debit": 0, "credit": amount},
        ]
    draft = DraftEntry(
        company_id=company_id,
        entry_date=date(income_year, 12, 31),
        memo=f"Skatteoppgjør: {settlement_type}",
        source=f"holding_action:tax_settlement:{settlement_type}",
        lines=lines,
    )
    ledger = NarrowLedger()
    ledger.create_draft(draft)
    posted = ledger.post(draft.id)
    action = StructuredAction(
        company_id=company_id,
        income_year=income_year,
        action_type="tax_settlement",
        status="posted",
        payload={"amount": amount, "settlement_type": settlement_type},
        ledger_entry_id=posted.id,
        created_by=actor_id,
    )
    workspace = _with_audit(
        workspace.model_copy(
            update={
                "posted_entries": workspace.posted_entries + (posted,),
                "structured_actions": workspace.structured_actions + (action,),
            }
        ),
        actor_id,
        AuditCategory.ACTION,
        "tax_settlement_recorded",
        f"Skatteoppgjør lagret: {settlement_type}.",
    )
    return store.replace_workspace(workspace)


def assign_founder_billing(store: WorkspaceStore, actor_id: str, company_id: str, *, cohort_number: int) -> CompanyWorkspace:
    workspace = store.get_workspace(actor_id, company_id, roles=(WorkspaceRole.OWNER,))
    account = assign_founder_pricing(company_id, cohort_number=cohort_number)
    workspace = _with_audit(
        workspace.model_copy(update={"billing_account": account}),
        actor_id,
        AuditCategory.BILLING,
        "founder_pricing_assigned",
        f"Founder-prising tildelt: {cohort_number}.",
    )
    return store.replace_workspace(workspace)


def request_filing_package_payment(store: WorkspaceStore, actor_id: str, company_id: str, *, filing_ready: bool) -> CompanyWorkspace:
    workspace = store.get_workspace(actor_id, company_id, roles=(WorkspaceRole.OWNER,))
    account = workspace.billing_account or assign_standard_pricing(company_id)
    gate = production_filing_gate(account, filing_ready=filing_ready)
    if not gate.charge_allowed:
        raise ValueError(gate.message)
    updated = account.model_copy(update={"subscription_active": True, "filing_package_paid": True})
    workspace = _with_audit(
        workspace.model_copy(update={"billing_account": updated}),
        actor_id,
        AuditCategory.BILLING,
        "filing_package_paid",
        "Filingpakke betalt.",
    )
    return store.replace_workspace(workspace)


def dashboard_for_company(
    store: WorkspaceStore,
    actor_id: str,
    company_id: str,
    *,
    income_year: int,
    today: date | None = None,
) -> WorkspaceDashboard:
    workspace = store.get_workspace(actor_id, company_id)
    annual_data = _annual_data_from_workspace(workspace, income_year)
    annual = simulate_annual_accounts(annual_data)
    tax = simulate_tax_return(annual_data)
    override_issues = tuple(
        f"Manuell overstyring: {override.field_target} ({override.risk_level})"
        for override in workspace.filing_overrides
        if override.income_year == income_year
    )
    bank_issues = tuple(
        "Uavstemte banktransaksjoner finnes."
        for _ in [None]
        if any(item.income_year == income_year and not item.is_matched for item in workspace.bank_transactions)
    )
    filings = (
        FilingDashboardItem(
            filing="aksjonærregisteroppgaven",
            status=FilingStatus.BLOCKED if _has_blocking_overrides(workspace, income_year) else FilingStatus.READY,
            issues=override_issues + bank_issues,
            preview=None,
        ),
        _filing_item(annual, override_issues + bank_issues),
        _filing_item(tax, override_issues + bank_issues),
    )
    return WorkspaceDashboard(
        company=workspace.company,
        support_boundary=workspace.support_boundary,
        filings=filings,
        deadlines=deadline_states(income_year, today=today),
        document_count=len([item for item in workspace.documents if item.income_year == income_year]),
        unreconciled_bank_transactions=len(
            [item for item in workspace.bank_transactions if item.income_year == income_year and not item.is_matched]
        ),
        archive_ready=True,
    )


def export_workspace_archive(store: WorkspaceStore, actor_id: str, company_id: str, *, income_year: int) -> CompanyArchive:
    workspace = store.get_workspace(actor_id, company_id)
    data = _annual_data_from_workspace(workspace, income_year)
    simulations = (simulate_annual_accounts(data), simulate_tax_return(data))
    return build_company_archive(data, filing_simulations=simulations)


def deadline_states(income_year: int, *, today: date | None = None) -> tuple[DeadlineState, ...]:
    current = today or date.today()
    deadlines = (
        ("aksjonærregisteroppgaven", date(income_year + 1, 1, 31)),
        ("skattemelding for AS", date(income_year + 1, 5, 31)),
        ("årsregnskap", date(income_year + 1, 7, 31)),
    )
    states = []
    for filing, deadline in deadlines:
        if current > deadline:
            status = FilingStatus.OVERDUE
            message = "Fristen er passert. Send inn så snart som mulig; gebyr kan gjelde."
        elif (deadline - current).days <= 30:
            status = FilingStatus.WARNING
            message = "Fristen nærmer seg."
        else:
            status = FilingStatus.DRAFT
            message = "Frist kommer senere."
        states.append(DeadlineState(filing=filing, deadline=deadline, status=status, message=message))
    return tuple(states)


def validate_annual_public_data(data: AnnualData, *, source: str = "public/synthetic") -> dict[str, Any]:
    annual = assess_annual_accounts_readiness(data)
    tax = assess_tax_return_readiness(data)
    mismatches: list[str] = []
    if round(data.bank_balance + data.investment_balance, 2) < 0:
        mismatches.append("negative_assets")
    outcome = "blocked" if not annual.is_ready or not tax.is_ready else "mismatch" if mismatches else "pass"
    return {
        "source": source,
        "filings": [annual.model_dump(), tax.model_dump()],
        "outcome": outcome,
        "mismatches": mismatches,
        "limitations": [
            "Public and synthetic data cannot prove voucher completeness.",
            "Public and synthetic data cannot prove exact bank transaction classification.",
            "Public and synthetic data cannot prove parity with Fiken or accountant-submitted payloads.",
        ],
    }


def norwegian_label(value: str) -> str:
    labels = {
        "ready": "Klar",
        "warning": "Advarsel",
        "blocked": "Blokkert",
        "draft": "Utkast",
        "filed": "Innsendt",
        "overdue": "Forfalt",
        "review": "Gjennomgang",
        "readiness": "Filingstatus",
        "owner workflow": "Eierløype",
    }
    return labels.get(value.lower(), value)


def _membership(workspace: CompanyWorkspace, actor_id: str) -> CompanyMembership:
    for membership in workspace.memberships:
        if membership.actor_id == actor_id:
            return membership
    raise PermissionError("actor does not have access to company")


def _audit(company_id: str, actor_id: str, category: AuditCategory, action: str, message: str) -> AuditLogEvent:
    return AuditLogEvent(company_id=company_id, actor_id=actor_id, category=category, action=action, message=message)


def _with_audit(
    workspace: CompanyWorkspace,
    actor_id: str,
    category: AuditCategory,
    action: str,
    message: str,
) -> CompanyWorkspace:
    return workspace.model_copy(
        update={"audit_events": workspace.audit_events + (_audit(workspace.company.org_number, actor_id, category, action, message),)}
    )


def _stable_id(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(parts)))


def _assert_not_locked(workspace: CompanyWorkspace, income_year: int) -> None:
    if any(lock.income_year == income_year for lock in workspace.period_locks):
        raise ValueError("period is locked; create correction in an open period")


def _build_action_entry(action_input: Any) -> dict[str, Any]:
    if isinstance(action_input, AdminCostInput):
        return {"action_type": "admin_cost", "entry": build_admin_cost_entry(action_input)}
    if isinstance(action_input, DividendReceivedInput):
        result = build_dividend_received(action_input)
        return {"action_type": "dividend_received", "entry": result.entry, "result": result}
    if isinstance(action_input, SharePurchaseInput):
        result = build_share_purchase(action_input)
        return {"action_type": "share_purchase", "entry": result.entry, "result": result}
    if isinstance(action_input, ShareSaleInput):
        result = build_share_sale(action_input)
        return {"action_type": "share_sale", "entry": result.entry, "result": result}
    if isinstance(action_input, DividendToOwnerInput):
        result = build_dividend_to_owner(action_input)
        return {"action_type": "dividend_to_owner", "entry": result.entry, "result": result}
    if isinstance(action_input, ShareholderLoanInput):
        return {"action_type": "shareholder_loan", "entry": build_shareholder_loan(action_input)}
    raise TypeError("unsupported action input")


def _apply_investment_result(workspace: CompanyWorkspace, result: dict[str, Any], action: StructuredAction) -> CompanyWorkspace:
    if result["action_type"] == "share_purchase":
        position: InvestmentPosition = result["result"].position
        movement = InvestmentMovement(
            action_id=action.id,
            movement_type="purchase",
            movement_date=date.fromisoformat(action.payload["acquisition_date"]),
            share_delta=position.share_count,
            cost_basis_delta=position.cost_basis,
            amount=position.cost_basis,
        )
        registered = InvestmentRegisterPosition(
            id=position.id,
            company_id=position.company_id,
            name=position.name,
            tax_treatment=position.tax_treatment,
            org_number=position.org_number,
            share_count=position.share_count,
            cost_basis=position.cost_basis,
            movements=(movement,),
        )
        return workspace.model_copy(update={"investment_positions": workspace.investment_positions + (registered,)})
    if result["action_type"] == "share_sale":
        sale_result = result["result"]
        positions: list[InvestmentRegisterPosition] = []
        for position in workspace.investment_positions:
            if position.id != sale_result.updated_position.id:
                positions.append(position)
                continue
            movement = InvestmentMovement(
                action_id=action.id,
                movement_type="sale",
                movement_date=date.fromisoformat(action.payload["sale_date"]),
                share_delta=-float(action.payload["sold_share_count"]),
                cost_basis_delta=round(sale_result.updated_position.cost_basis - position.cost_basis, 2),
                amount=float(action.payload["proceeds"]),
            )
            positions.append(
                position.model_copy(
                    update={
                        "share_count": sale_result.updated_position.share_count,
                        "cost_basis": sale_result.updated_position.cost_basis,
                        "movements": position.movements + (movement,),
                    }
                )
            )
        return workspace.model_copy(update={"investment_positions": tuple(positions)})
    if result["action_type"] == "dividend_received":
        investment_id = action.payload["linked_investment_id"]
        positions = []
        for position in workspace.investment_positions:
            if position.id != investment_id:
                positions.append(position)
                continue
            movement = InvestmentMovement(
                action_id=action.id,
                movement_type="dividend",
                movement_date=date.fromisoformat(action.payload["paid_date"]),
                amount=float(action.payload["gross_amount"]),
            )
            positions.append(position.model_copy(update={"movements": position.movements + (movement,)}))
        return workspace.model_copy(update={"investment_positions": tuple(positions)})
    return workspace


def _manual_journal_risk(entry: DraftEntry) -> ManualJournalRisk:
    accounts = {line.account for line in entry.lines}
    blocked = {"2500", "8300"}
    warning = {"1800", "2000", "2050", "8070", "8090", "1370", "2255", "2800"}
    if accounts & blocked:
        return ManualJournalRisk.BLOCK
    if accounts & warning:
        return ManualJournalRisk.WARNING
    return ManualJournalRisk.NORMAL


def _annual_data_from_workspace(workspace: CompanyWorkspace, income_year: int) -> AnnualData:
    interview = YearEndInterviewAnswers(
        shares_owned_at_year_end=bool(workspace.investment_positions),
        bought_or_sold_shares=any(action.action_type in {"share_purchase", "share_sale"} for action in workspace.structured_actions),
        received_dividends=any(action.action_type == "dividend_received" for action in workspace.structured_actions),
        declared_owner_dividends=any(action.action_type == "dividend_to_owner" for action in workspace.structured_actions),
        shareholder_loans=any(action.action_type == "shareholder_loan" for action in workspace.structured_actions),
        paid_costs=any(action.action_type == "admin_cost" for action in workspace.structured_actions),
        bank_balance_confirmed=not any(item.income_year == income_year and not item.is_matched for item in workspace.bank_transactions),
        has_unpaid_items=False,
        general_meeting_approved=True,
        authority_to_submit_confirmed=workspace.company.confirmed_at is not None,
    )
    documents = tuple(
        DocumentRecord(
            id=document.id,
            document_type=document.document_type,
            name=document.name,
            status=document.status,
            storage_uri=document.storage_key,
        )
        for document in workspace.documents
        if document.income_year == income_year
    )
    return build_annual_data(
        company_id=workspace.company.org_number,
        income_year=income_year,
        interview=interview,
        posted_entries=tuple(entry for entry in workspace.posted_entries if entry.entry_date.year == income_year),
        documents=documents,
        confirmations=("identity_confirmed",) if workspace.company.confirmed_at else (),
    )


def _filing_item(simulation: FilingSimulation, extra_issues: tuple[str, ...]) -> FilingDashboardItem:
    issues = tuple(issue.message for issue in simulation.readiness.issues) + extra_issues
    status = FilingStatus.READY if simulation.readiness.is_ready and not extra_issues else FilingStatus.BLOCKED if not simulation.readiness.is_ready else FilingStatus.WARNING
    return FilingDashboardItem(filing=simulation.filing, status=status, issues=issues, preview=simulation.preview)


def _has_blocking_overrides(workspace: CompanyWorkspace, income_year: int) -> bool:
    return any(override.income_year == income_year and override.risk_level == "block" for override in workspace.filing_overrides)
