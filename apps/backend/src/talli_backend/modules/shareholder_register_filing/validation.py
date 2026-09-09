"""Pure RF public/synthetic validation classification, without filesystem I/O."""
from __future__ import annotations
from .public import Rf1086ValidationInput,Rf1086ValidationCaseResult,Rf1086ValidationReport
from .case_parser import parse_rf1086_case
from .readiness import assess_rf1086_readiness
from .rendering import generate_rf1086

_LIMITATIONS=(
    'Public and synthetic data cannot prove voucher completeness.',
    'Public and synthetic data cannot prove exact bank transaction classification.',
    'Public and synthetic data cannot prove parity with Fiken or accountant-submitted payloads.',
)
_ASSUMPTIONS=('RF-1086 launch subset','No production authority submission','Official XSD validation is separate')


def _validate_case(input: Rf1086ValidationInput) -> Rf1086ValidationCaseResult:
    if input.read_error is not None:
        return Rf1086ValidationCaseResult(input.case_path,None,'blocked',_ASSUMPTIONS,('Case validation failed: '+input.read_error,),0)
    try:
        case = parse_rf1086_case(input.contents)
    except ValueError as error:
        return Rf1086ValidationCaseResult(input.case_path,None,'blocked',_ASSUMPTIONS,(f'Case validation failed: {error}',),0)
    readiness = assess_rf1086_readiness(case)
    if not readiness.is_ready:
        return Rf1086ValidationCaseResult(input.case_path,case.case_id,'blocked',_ASSUMPTIONS,
            tuple(issue.message for issue in readiness.issues),0)
    documents = generate_rf1086(case)
    warnings = tuple(issue.message for issue in readiness.issues if issue.level=='warning')
    return Rf1086ValidationCaseResult(input.case_path,case.case_id,'warning' if warnings else 'pass',_ASSUMPTIONS,
        warnings,1+len(documents.underskjema_xml))


def validate_cases(inputs: tuple[Rf1086ValidationInput, ...], *, source: str='public/synthetic') -> Rf1086ValidationReport:
    return Rf1086ValidationReport('aksjonærregisteroppgaven',source,_LIMITATIONS,tuple(_validate_case(input) for input in inputs))
