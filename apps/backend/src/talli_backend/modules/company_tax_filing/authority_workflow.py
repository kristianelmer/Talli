"""Company Tax retry, terminal-status and pending-receipt decisions."""
from __future__ import annotations

from .public import CompanyTaxAuthority, CompanyTaxReturnAuthorityError


async def wait_for_validation(client: CompanyTaxAuthority, *, attempts=20, sleep, **values):
    if type(attempts) is not int or not 1 <= attempts <= 120:
        raise ValueError("Validation attempts must be between 1 and 120.")
    for attempt in range(attempts):
        status = (await client.get_validation_status(**values))["status"]
        if status == "FERDIG":
            return await client.get_validation_result(**values)
        if status in ("AVBRUTT", "FEILET"):
            raise CompanyTaxReturnAuthorityError("Validation ended unsuccessfully.", code="COMPANY_TAX_VALIDATION_"+status, retryable=status == "FEILET")
        if status not in ("NY", "OPPRETTET", "KJOERER", "VENTER"):
            raise CompanyTaxReturnAuthorityError("Unknown validation status.", code="COMPANY_TAX_VALIDATION_STATUS_UNKNOWN")
        if attempt < attempts-1:
            await sleep(2)
    raise CompanyTaxReturnAuthorityError("Validation polling timed out.", code="COMPANY_TAX_VALIDATION_TIMEOUT", retryable=True)


async def wait_for_feedback(client: CompanyTaxAuthority, *, instance_id, attempts=30, sleep):
    if type(attempts) is not int or not 1 <= attempts <= 120:
        raise ValueError("Feedback attempts must be between 1 and 120.")
    for attempt in range(attempts):
        try:
            return await client.get_feedback_receipt(instance_id=instance_id)
        except CompanyTaxReturnAuthorityError as error:
            if error.code != "COMPANY_TAX_FEEDBACK_PENDING":
                raise
        if attempt < attempts-1:
            await sleep(2)
    raise CompanyTaxReturnAuthorityError("Feedback polling timed out.", code="COMPANY_TAX_FEEDBACK_TIMEOUT", retryable=True)


async def wait_for_clean_envelope(client: CompanyTaxAuthority, instance_id, *, attempts=30, sleep):
    for attempt in range(attempts):
        scan = await client.get_envelope_scan(instance_id=instance_id)
        if scan["fileScanResult"] == "Clean":
            return scan
        if attempt < attempts-1:
            await sleep(2)
    raise CompanyTaxReturnAuthorityError("Envelope scan polling timed out.", code="COMPANY_TAX_ENVELOPE_SCAN_TIMEOUT", retryable=True)
