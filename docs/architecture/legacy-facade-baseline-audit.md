# Frozen legacy-facade baseline audit

Issue #186 audits the compatibility registry that existed at revision
`d331ee2717d1eeacef0d81db42b9d4fb5848b408`. The source revision contains all
20 records below. The frozen baseline contains the same 237 exact scopes and is
pinned by `sha256:cbcf06de635da8e2715cb6f0832a9d525be9aed58ec8f32b5e59bda8dfa7cbbe`.

The audit assigns every record to exactly one ADR-0013 migration capability and
one removal issue. Each capability has one symbolic canonical implementation,
`web:legacy-runtime:<capability>`. Multiple records for a capability partition
the removal tickets; they do not authorize multiple writers. The architecture
checker reconciles every active scope against the real source tree and rejects
an unregistered or ambiguous persistence path.

| Frozen record | Capability | Removal | Canonical implementation | Scopes |
| --- | --- | --- | --- | ---: |
| `compat-company-onboarding-persistence` | `company_access` | #138 | `web:legacy-runtime:company_access` | 3 |
| `compat-ledger-persistence` | `ledger` | #139 | `web:legacy-runtime:ledger` | 25 |
| `compat-banking-persistence` | `banking` | #140 | `web:legacy-runtime:banking` | 10 |
| `compat-investment-purchase-persistence` | `investments` | #141 | `web:legacy-runtime:investments` | 3 |
| `compat-investment-sale-persistence` | `investments` | #142 | `web:legacy-runtime:investments` | 4 |
| `compat-investment-stage-exit-persistence` | `investments` | #143 | `web:legacy-runtime:investments` | 2 |
| `compat-documents-persistence` | `documents` | #147 | `web:legacy-runtime:documents` | 15 |
| `compat-owner-dividend-persistence` | `corporate_governance` | #144 | `web:legacy-runtime:corporate_governance` | 2 |
| `compat-shareholder-loan-persistence` | `corporate_governance` | #145 | `web:legacy-runtime:corporate_governance` | 1 |
| `compat-corporate-governance-persistence` | `corporate_governance` | #148 | `web:legacy-runtime:corporate_governance` | 19 |
| `compat-billing-persistence` | `billing` | #137 | `web:legacy-runtime:billing` | 19 |
| `compat-authority-connections-persistence` | `authority_connections` | #150 | `web:legacy-runtime:authority_connections` | 16 |
| `compat-rf1086-persistence` | `shareholder_register_filing` | #151 | `web:legacy-runtime:shareholder_register_filing` | 35 |
| `compat-tax-settlement-persistence` | `company_tax_filing` | #146 | `web:legacy-runtime:company_tax_filing` | 1 |
| `compat-company-tax-persistence` | `company_tax_filing` | #152 | `web:legacy-runtime:company_tax_filing` | 2 |
| `compat-annual-accounts-persistence` | `annual_accounts_filing` | #153 | `web:legacy-runtime:annual_accounts_filing` | 2 |
| `compat-annual-compliance-persistence` | `annual_compliance` | #149 | `web:legacy-runtime:annual_compliance` | 22 |
| `compat-audit-persistence` | `audit` | #155 | `web:legacy-runtime:audit` | 30 |
| `compat-notification-persistence` | `notifications` | #156 | `web:legacy-runtime:notifications` | 2 |
| `compat-company-archive-persistence` | `company_archive` | #157 | `web:legacy-runtime:company_archive` | 24 |

This baseline changes architecture metadata and enforcement only. It does not
activate a provider, change business behavior, modify persistence, process
customer data, or authorize a production action.
