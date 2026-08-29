# AGENTS.md

Guidance for AI agents working in this repository.

## Cost approval guardrail

Before taking any action that could incur a charge, stop and obtain Kristian's
explicit approval. This includes one-time fees, subscriptions, usage-based API or
cloud costs, certificate purchases, registration fees, payment-provider charges,
and paid third-party services.

The warning must identify the provider, the expected amount or best available
estimate, whether the charge is recurring or usage-based, and any practical free
or cheaper alternative. If the cost is uncertain, treat the action as potentially
chargeable and ask before proceeding. General authorization to continue, deploy,
or finish the product is not authorization to spend money.

### GitHub and Vercel standing no-cost authority

Kristian has confirmed that ordinary GitHub and Vercel operations for Talli are
free and pre-authorized. Git pushes, GitHub API/issue/Actions use, and automatic
Vercel Preview deployments do not trigger the cost-approval gate and must not
pause autonomous work.

Treat this as a standing owner rule until Kristian explicitly revokes it. Only a
provider flow that explicitly presents a paid purchase, plan upgrade, add-on, or
monetary charge requires separate cost approval.

## Agent skills

### Issue tracker

Issues and PRDs are tracked in GitHub Issues via the `gh` CLI; external PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles map to identically-named labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
