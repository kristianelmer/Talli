"""Tax-owned normalization of the existing filing controls."""
from dataclasses import replace

from .public import CompanyTaxError

_JS_SPACE = '\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'


def _trim(value):
    if not isinstance(value, str):
        raise CompanyTaxError.invalid_input()
    return value.strip(_JS_SPACE)


def normalize_override(command):
    result = replace(command, field_target=_trim(command.field_target), old_value=_trim(command.old_value),
        new_value=_trim(command.new_value), reason=_trim(command.reason))
    if result.owner_confirmed is not True:
        raise CompanyTaxError.invalid_input('Overstyring må bekreftes av eier')
    if not result.field_target:
        raise CompanyTaxError.invalid_input('Feltmål mangler for filing-overstyring.')
    if not (result.old_value or result.new_value):
        raise CompanyTaxError.invalid_input('Gammel eller ny verdi må fylles ut for filing-overstyring.')
    if not result.reason:
        raise CompanyTaxError.invalid_input('Begrunnelse mangler for filing-overstyring.')
    if result.risk_level not in ('advisory', 'warning', 'block'):
        raise CompanyTaxError.invalid_input('Ugyldig risikonivå for filing-overstyring.')
    return result


def normalize_review(command):
    result = replace(command, body=_trim(command.body))
    if result.severity not in ('advisory', 'hard_block'):
        raise CompanyTaxError.invalid_input('Ugyldig kommentaralvorlighet')
    if not result.body:
        raise CompanyTaxError.invalid_input('Kommentar mangler')
    return result


def normalize_test_evidence(command):
    if command.environment not in ('test', 'manual_evidence'):
        raise CompanyTaxError.invalid_input('Ugyldig testmiljø')
    if command.status not in ('accepted', 'rejected', 'blocked', 'pending'):
        raise CompanyTaxError.invalid_input('Ugyldig teststatus.')
    result = replace(command, test_reference=_trim(command.test_reference), feedback_summary=_trim(command.feedback_summary),
        **{key: _trim(getattr(command, key)) or None if getattr(command, key) is not None else None
           for key in ('receipt_reference', 'archive_reference', 'evidence_url', 'payload_hash')})
    if not result.test_reference:
        raise CompanyTaxError.invalid_input('Testreferanse mangler.')
    return result
