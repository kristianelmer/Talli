"""Bracketing known reads bind an owner review to exact instance/file originals."""
from dataclasses import dataclass

from talli_backend.shared.kernel import Timestamp
from .delivery import annual_accounts_delivery_digest
from .delivery_events import AnnualAccountsDeliveryAction,AnnualAccountsDeliveryFrameRecord,AnnualAccountsFrameKind,AnnualAccountsDeliveryObservation
from .delivery_originals import AnnualAccountsReadPurpose as Purpose,inspect_annual_accounts_instance,inspect_annual_accounts_validation


@dataclass(frozen=True,slots=True)
class AnnualAccountsDeliveryFrameInspection:
    kind: AnnualAccountsFrameKind
    instance_id: str
    main_data_id: str
    accounts_data_id: str
    pdf_data_ids: tuple[str,...]
    signature_data_id: str | None
    review_sha256: str
    prerequisite_sha256: str
    first_requested_at: Timestamp
    first_observed_at: Timestamp
    last_observed_at: Timestamp
    validation_issues: tuple[object,...]
    has_validation_errors: bool | None

    def assert_fresh(self,now,*,after):
        if (type(now) is not Timestamp or type(after) is not Timestamp
                or not after.value<=self.first_requested_at.value<=self.first_observed_at.value<=self.last_observed_at.value<=now.value
                or (now.value-self.first_requested_at.value).total_seconds()>60):raise ValueError('Accounts read frame is not fresh for this operation.')

    def assert_action(self,action):
        kinds={AnnualAccountsDeliveryAction.UPLOAD_MAIN_FORM:AnnualAccountsFrameKind.CREATE_TARGET,
            AnnualAccountsDeliveryAction.UPLOAD_COMPANY_ACCOUNTS:AnnualAccountsFrameKind.MAIN_UPLOADED,
            AnnualAccountsDeliveryAction.CONFIRM:AnnualAccountsFrameKind.UPLOAD_REVIEW,
            AnnualAccountsDeliveryAction.SIGN:AnnualAccountsFrameKind.SIGN_REVIEW}
        if type(action) is not AnnualAccountsDeliveryAction or kinds.get(action) is not self.kind:raise ValueError('Accounts frame does not authorize this operation kind.')
        if action in (AnnualAccountsDeliveryAction.CONFIRM,AnnualAccountsDeliveryAction.SIGN) and self.has_validation_errors is not False:
            raise ValueError('Accounts validation does not permit a process mutation.')


def inspect_annual_accounts_delivery_frame(frame,observations,*,draft,known_instance,schemas):
    """Historical byte inspection only. Callers separately check freshness/admission."""
    if type(frame) is not AnnualAccountsDeliveryFrameRecord or not isinstance(observations,(tuple,list)):raise ValueError()
    frame.binding.assert_draft(draft)
    indexed={}
    for row in observations:
        if type(row) is not AnnualAccountsDeliveryObservation or row.sha256 in indexed:raise ValueError('Accounts observation references are ambiguous.')
        indexed[row.sha256]=row
    if any(reference not in indexed for reference in frame.observation_sha256):raise ValueError('Accounts frame original is missing.')
    selected=tuple(indexed[reference] for reference in frame.observation_sha256)
    originals=tuple(row.original for row in selected)
    if any(row.http_status!=200 or row.failure_code is not None or row.body_base64 is None for row in originals):
        raise ValueError('Accounts frame contains an uncertain or failed read.')
    if any(row.binding!=frame.binding or row.original.instance_id!=known_instance for row in selected):raise ValueError('Accounts frame scope differs.')
    if any(a.observed_at.value>b.observed_at.value for a,b in zip(originals,originals[1:])):
        raise ValueError('Accounts read frame order is invalid.')
    metas=tuple(row for row in originals if row.purpose is Purpose.INSTANCE)
    if frame.kind is AnnualAccountsFrameKind.CREATE_TARGET:
        if len(metas)!=1 or len(originals)!=1:raise ValueError('Creation-target frame contains unexpected reads.')
    elif (len(metas)!=2 or originals[0] is not metas[0] or originals[-1] is not metas[-1]
            or metas[0].sha256!=metas[-1].sha256):raise ValueError('Accounts instance changed during the bracketing reads.')
    if len(metas)==2 and any(not metas[0].observed_at.value<=row.requested_at.value<=row.observed_at.value<=metas[-1].requested_at.value
                             for row in originals[1:-1]):raise ValueError('Accounts file requests are outside the metadata bracket.')
    metadata=inspect_annual_accounts_instance(metas[-1],organization_number=draft.source.organization_number)
    if len(metas)==2:inspect_annual_accounts_instance(metas[0],organization_number=draft.source.organization_number)
    if metadata.instance_id!=known_instance:raise ValueError()
    elements={row.data_id:row for row in metadata.data}
    main,=tuple(row for row in metadata.data if row.data_type=='Hovedskjema')
    accounts,=tuple(row for row in metadata.data if row.data_type=='Underskjema')
    pdfs=tuple(row for row in metadata.data if row.data_type=='ref-data-as-pdf')
    signatures=tuple(row for row in metadata.data if row.data_type=='signature')
    purposes={purpose:tuple(row for row in originals if row.purpose is purpose) for purpose in Purpose}
    expected={Purpose.INSTANCE:1 if frame.kind is AnnualAccountsFrameKind.CREATE_TARGET else 2, Purpose.MAIN_FORM:0,
        Purpose.COMPANY_ACCOUNTS:0,Purpose.VALIDATION:0,Purpose.PDF:0,Purpose.SIGNATURE:0}
    if frame.kind is not AnnualAccountsFrameKind.CREATE_TARGET:expected[Purpose.MAIN_FORM]=1
    if frame.kind in (AnnualAccountsFrameKind.UPLOAD_REVIEW,AnnualAccountsFrameKind.SIGN_REVIEW,AnnualAccountsFrameKind.ARCHIVE):expected[Purpose.COMPANY_ACCOUNTS]=1
    if frame.kind in (AnnualAccountsFrameKind.UPLOAD_REVIEW,AnnualAccountsFrameKind.SIGN_REVIEW):expected[Purpose.VALIDATION]=1
    if frame.kind in (AnnualAccountsFrameKind.SIGN_REVIEW,AnnualAccountsFrameKind.ARCHIVE):
        if not pdfs:raise ValueError('Accounts generated PDF originals are missing.')
        expected[Purpose.PDF]=len(pdfs)
    if frame.kind is AnnualAccountsFrameKind.ARCHIVE:
        if len(signatures)!=1:raise ValueError('Accounts terminal signature original is missing.')
        expected[Purpose.SIGNATURE]=1
    if any(len(purposes[purpose])!=count for purpose,count in expected.items()):raise ValueError('Accounts frame read extent differs.')
    file_ids=set()
    for row in originals:
        if row.data_id is None:continue
        if row.data_id in file_ids:raise ValueError('Accounts frame repeats a file original.')
        if row.data_id not in elements:raise ValueError('Accounts frame file is not a known metadata reference.')
        file_ids.add(row.data_id);element=elements[row.data_id]
        kind={Purpose.MAIN_FORM:'Hovedskjema',Purpose.COMPANY_ACCOUNTS:'Underskjema',Purpose.PDF:'ref-data-as-pdf',Purpose.SIGNATURE:'signature'}[row.purpose]
        if (element.data_type!=kind or element.content_type!=row.media_type or element.size_bytes!=len(row.raw_bytes)
                or element.size_bytes==0):raise ValueError('Accounts original does not match its known metadata reference.')
        if row.purpose is Purpose.MAIN_FORM and row.sha256!=draft.inspection.main_form_sha256:raise ValueError('Accounts main original differs from reviewed XML.')
        if row.purpose is Purpose.COMPANY_ACCOUNTS and row.sha256!=draft.inspection.company_accounts_sha256:raise ValueError('Accounts company original differs from reviewed XML.')
    if expected[Purpose.COMPANY_ACCOUNTS]:
        inspection=schemas.validate_pair(purposes[Purpose.MAIN_FORM][0].raw_bytes,purposes[Purpose.COMPANY_ACCOUNTS][0].raw_bytes,
            organization_number=draft.source.organization_number,income_year=int(draft.source.income_year))
        if inspection!=draft.inspection:raise ValueError('Accounts exact pair inspection differs from the prepared draft.')
    if frame.kind is AnnualAccountsFrameKind.ARCHIVE:
        if metadata.task is not None or metadata.ended_at is None or metadata.archived is not True:raise ValueError('Accounts technical archive is not positively observed.')
    else:
        task='Signering' if frame.kind is AnnualAccountsFrameKind.SIGN_REVIEW else 'Utfylling'
        if metadata.task!=task or metadata.ended_at is not None or metadata.archived or signatures:
            raise ValueError('Accounts process is not at the expected unsigned task.')
    issues=inspect_annual_accounts_validation(purposes[Purpose.VALIDATION][0]) if expected[Purpose.VALIDATION] else ()
    errors=any(row['severity']=='error' for row in issues) if expected[Purpose.VALIDATION] else None
    review_hash=annual_accounts_delivery_digest({'version':'annual-accounts-frame-review-v1','draftSha256':draft.sha256,
        'kind':frame.kind.value,'originals':tuple((row.purpose.value,row.instance_id,row.data_id,row.sha256) for row in originals)})
    return AnnualAccountsDeliveryFrameInspection(frame.kind,known_instance,main.data_id,accounts.data_id,tuple(row.data_id for row in pdfs),
        signatures[0].data_id if signatures else None,review_hash,frame.sha256,originals[0].requested_at,originals[0].observed_at,originals[-1].observed_at,issues,errors)
