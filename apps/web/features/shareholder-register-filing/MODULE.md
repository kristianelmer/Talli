# Shareholder register filing presentation

The feature uses the generated API client to present RF-1086 previews, review,
simulation, approvals and retained production history. Python owns validation,
payloads, confirmation gates and lifecycle decisions. Authority credentials and
business persistence stay behind the backend boundary.

The two shipped v1 Send and recovery operation names remain unchanged.

<!-- architecture-inventory
{"publicEntryPoints":["@/features/shareholder-register-filing","apps/web/features/shareholder-register-filing","apps/web/features/shareholder-register-filing/index.ts"],"routes":[],"apiOperations":["legacyRf1086ReconcileFeedback","legacyRf1086SendApprovedFiling","rf1086AcknowledgeReviewComment","rf1086AddReviewComment","rf1086ApproveProduction","rf1086ConfirmFilingPermission","rf1086ConfirmSimulation","rf1086GeneratePreview","rf1086GetArchiveSource","rf1086Preview","rf1086RecordOverride","rf1086RecordTestEvidence","rf1086Workspace"],"dependencies":[]}
-->

`rf1086GetArchiveSource` transports only the original archive source extent for one company/year, including its company-wide comments and permissions.
