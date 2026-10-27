"""A temporary auth dependency failure keeps billing reads fail-closed and retryable."""

import asyncio

import pytest

from talli_backend.adapters.supabase_annual_billing import SupabaseAnnualBillingAdapter
from talli_backend.adapters.supabase_billing import SupabaseBillingAdapter
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration
from talli_backend.application.billing_session import BillingAuthenticationError
from talli_backend.application.ledger_session import LedgerAuthenticationError
from talli_backend.modules.billing.public import BillingError, BillingErrorCode
from talli_backend.modules.ledger.public import LedgerError
from talli_backend.shared.kernel import ErrorCategory


@pytest.mark.parametrize("factory", [SupabaseBillingAdapter, SupabaseAnnualBillingAdapter])
def test_billing_session_maps_auth_outage_to_dependency_unavailable(factory):
    adapter = factory(LedgerSupabaseConfiguration(url="", anon_key="", database_url=""))

    async def unavailable(_token):
        raise LedgerError.unavailable()

    authentication = (
        adapter._authentication if isinstance(adapter, SupabaseAnnualBillingAdapter)
        else adapter._ledger_authentication
    )
    authentication.session = unavailable

    with pytest.raises(BillingError) as failure:
        asyncio.run(adapter.session("bearer"))

    assert failure.value.code == BillingErrorCode.DEPENDENCY_UNAVAILABLE
    assert failure.value.category == ErrorCategory.DEPENDENCY_UNAVAILABLE


@pytest.mark.parametrize("factory", [SupabaseBillingAdapter, SupabaseAnnualBillingAdapter])
def test_billing_session_preserves_invalid_bearer(factory):
    adapter = factory(LedgerSupabaseConfiguration(url="", anon_key="", database_url=""))

    async def invalid(_token):
        raise LedgerAuthenticationError()

    authentication = (
        adapter._authentication if isinstance(adapter, SupabaseAnnualBillingAdapter)
        else adapter._ledger_authentication
    )
    authentication.session = invalid

    with pytest.raises(BillingAuthenticationError):
        asyncio.run(adapter.session("bearer"))


@pytest.mark.parametrize("factory", [SupabaseBillingAdapter, SupabaseAnnualBillingAdapter])
def test_billing_session_does_not_relabel_other_ledger_failures(factory):
    adapter = factory(LedgerSupabaseConfiguration(url="", anon_key="", database_url=""))

    async def forbidden(_token):
        raise LedgerError.forbidden()

    authentication = (
        adapter._authentication if isinstance(adapter, SupabaseAnnualBillingAdapter)
        else adapter._ledger_authentication
    )
    authentication.session = forbidden

    with pytest.raises(LedgerError) as failure:
        asyncio.run(adapter.session("bearer"))
    assert failure.value.category == ErrorCategory.FORBIDDEN
