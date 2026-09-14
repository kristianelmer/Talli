A narrow lifecycle-oracle correction is appropriate; no superuser cleanup or new security-definer is justified.

At55f5abbdcb0f4d638f26aea093db13722ef922c5, apply() requires unchanged pg_auth_members after expansion (test_annual_accounts_filing_lifecycle.py:49–55). All28 cases fail there with two additional tuples shaped (new-role,16384,10,true,false,false). Expansion explicitly creates two restricted roles before borrowing/restoring grants (20260914090244_annual_accounts_filing_expand.sql:19–41,285–291).

PostgreSQL17 documents that non-superuser CREATEROLE creates a bootstrap-superuser-owned ADMIN grant to the creator, without SET/INHERIT; the creator cannot revoke or alter it. ADMIN remains real management authority, including ability to grant execution membership later. Describe this as expected role-creation administration, not “no privilege.” [Official role attributes](https://www.postgresql.org/docs/17/role-attributes.html).

The safe assertion is exact post-state = exact pre-state ∪ exact expected creation grants:

- Only the named expansion artifact may allow additions, and only for its two explicitly declared roles positively absent in the pre-execution catalog. Bind each new OID to its exact role name and required restricted attributes.
- Capture the effective creating principal/OID and CREATEROLE/non-superuser status before execution. Require that principal as member, the verified bootstrap grantor (OID10), and ADMIN=true, INHERIT=false, SET=false. A superuser-created role expects no such addition.
- Preserve every preexisting membership tuple and grantor/options exactly. No exception for existing roles, later artifacts, cutover, rollback or temporary self-granted memberships. Keep the outer transaction rollback’s original unqualified equality and role/schema absence checks.
- Reject extra grants, changed options, wrong identities or undeclared roles. Include zero/one/two newly created-role controls, existing-role replay and borrowed-grant leakage negatives. Nonempty createrole_self_grant can add execution access; require its empty/default setting or reject its additional grants explicitly. [Official setting](https://www.postgresql.org/docs/17/runtime-config-client.html#GUC-CREATEROLE-SELF-GRANT).

This distinguishes authorized owner creation from temporary borrowing under ADR0011/0013 and #132; it is not an authorization/RLS exception. The minimum correction belongs in the test oracle, with exact non-superuser and existing-role runtime evidence. Keep55f’s failed gate unchanged and rerun the mandatory lifecycle/full gates after correction.

Read-only source/log/documentation assessment only. No database or role mutation, implementation edit, runtime reproduction or stage-exit credit.
