# Accounts role creation and grant restoration correction

The full 55f5abbd gate passed preceding stages and reached Accounts SQL, where all 28 original tests failed during expansion setup. The non-superuser CREATEROLE runner received PostgreSQL-required bootstrap ADMIN grants on the two freshly created roles. Earlier clone runs had preexisting global roles and did not cover that state. The original failed gate transcript is preserved; it provides no complete exit credit.

The exact membership assertion now permits only the bootstrap ADMIN=true, INHERIT=false, SET=false tuple for each declared Accounts role positively absent before that expansion, with the captured creator and verified bootstrap superuser OID10. All prior memberships and all other artifacts remain exact. The expansion clears transaction-local createrole_self_grant so optional ambient SET/INHERIT self-grants cannot arise. ADMIN is explicit role-management authority and is not described as harmless execution isolation.

A disposable PostgreSQL17.11 probe reproduces required creator ADMIN, inability to revoke the bootstrap grant, exact removal of temporary self-grants, and superuser creation without new memberships. Its container and volume were removed. The original fresh-role fixture reproduces the failure and then passes; all temporary role renames are rolled back, preserving original names, OIDs and memberships.

New tests also exposed a real restoration defect in six expansion artifacts: casting JSON Boolean text to PostgreSQL boolean caused format(%s) to emit invalid GRANT option tokens t/f. Passing the preserved JSON text emits true/false. All six unpublished artifacts are corrected. Full expansion, cutover, contract, rollback and re-cutover preserve preexisting direct grants exactly.

The final owned-local lifecycle run passes 41 tests, including the original 28. New controls cover zero/one/two existing roles, ambient self-grant options, replay rejection, prior INHERIT false/true, wrong grantor/recipient, added SET/INHERIT and changed preexisting grants. Original intermediate failures and the earlier 40-test successful run remain separate. Every fixture verifies outer rollback, original role identities and absence of Accounts schema/company.

Original independent design reviews are included as design-only evidence. The original f1e standards review and producers are adopted unchanged here, complementing the spec review in journal-reviews. This correction still requires independent implementation review and two complete immutable release gates before protected integration. No hosted, provider or production action occurred.

Primary engine references: https://www.postgresql.org/docs/17/role-attributes.html and https://www.postgresql.org/docs/17/runtime-config-client.html .
