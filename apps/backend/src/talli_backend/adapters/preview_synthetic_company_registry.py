"""Opt-in registry facts for the one approved, owned private Preview fixture."""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from types import MappingProxyType

from talli_backend.modules.company_access.public import (
    CompanyRegistryGateway,
    CompanyRegistryIdentity,
    company_registry_adapter,
)

_CONFIG = "TALLI_PREVIEW_SYNTHETIC_REGISTRY_IDENTITY"
_PROJECT = "prj_u28yRnkslspXi3LSEDQHvTz8EWCD"
_SUPABASE_URL = "https://pkpyyxryfhfehrbhbynp.supabase.co"
# This invalid organization number belongs to the already-provisioned private fixture.
_ORG_NUMBER = "992803750"
_CLOSED_MODES = {
    "TALLI_RF1086_PRODUCTION_ENABLED": "false",
    "TALLI_AUTHORITY_OPS_ENABLED": "false",
    "TALLI_ANNUAL_BILLING_MODE": "off",
    "TALLI_ANNUAL_CHECKOUT_RECONCILIATION_MODE": "off",
    "TALLI_VALIDATION_OBSERVATION_MODE": "off",
    "TALLI_COMPANY_TEST_RETENTION_MODE": "off",
}
_FIELDS = frozenset(("org_number", "name", "entity_type", "address", "postal_code", "city", "status_text", "source"))


@company_registry_adapter(CompanyRegistryGateway)
class PreviewSyntheticCompanyRegistryAdapter:
    def __init__(self, fallback: CompanyRegistryGateway, identity: CompanyRegistryIdentity) -> None:
        self._fallback = fallback
        self._identity = MappingProxyType(identity.model_dump())

    @classmethod
    def from_environment(cls, fallback: CompanyRegistryGateway) -> CompanyRegistryGateway:
        raw = os.environ.get(_CONFIG)
        if raw is None:
            return fallback
        # Reject accidental Production, custom-environment, project or database reuse.
        if (
            os.environ.get("VERCEL") != "1"
            or os.environ.get("VERCEL_ENV") != "preview"
            or os.environ.get("VERCEL_TARGET_ENV") != "preview"
            or os.environ.get("VERCEL_PROJECT_ID") != _PROJECT
            or os.environ.get("SUPABASE_URL") != _SUPABASE_URL
            or any(os.environ.get(key) != value for key, value in _CLOSED_MODES.items())
            or len(raw) > 4096
        ):
            raise ValueError("Synthetic registry requires the designated private Preview")
        try:
            value = json.loads(raw)
            if not isinstance(value, dict) or set(value) != _FIELDS:
                raise ValueError()
            identity = CompanyRegistryIdentity.model_validate(value)
        except (ValueError, TypeError):
            raise ValueError("Synthetic registry identity is invalid") from None
        if (
            identity.org_number != _ORG_NUMBER
            or identity.source != "browser_test"
            or identity.entity_type != "AS"
            or identity.status_text != "aktiv"
            or not identity.name.lower().startswith("synthetic private preview ")
            or len(identity.name) > 256
            or len(identity.address) > 512
            or len(identity.postal_code) > 4
            or len(identity.city) > 128
        ):
            raise ValueError("Synthetic registry identity is outside the approved fixture")
        return cls(fallback, identity)

    async def lookup_company(self, org_number: str) -> Mapping[str, object]:
        if org_number == _ORG_NUMBER:
            return dict(self._identity)
        return await self._fallback.lookup_company(org_number)
