# Talli product design direction

## Status

Approved direction, pending review of this written record.

## Objective

Define the default visual and interaction character for Talli before documenting or rebuilding the interface system. The direction must help an owner complete annual reporting for a simple Norwegian holding AS correctly, seamlessly, and inexpensively.

## Chosen direction: Quiet confidence

Talli will use a calm, familiar product interface with strong hierarchy, restrained color, and an immediately understandable navigation model. The product should feel smooth and systemized rather than decorated. The interface earns trust by making progress, next actions, validation, and completion states easy to scan.

This direction was chosen after comparing three distinct approaches:

- **Quiet confidence:** calm, familiar, navigation-first, and reassuring.
- **Modern ledger:** denser, sharper, and more operational.
- **Guided focus:** highly linear with minimal persistent navigation.

The user explored Modern ledger before choosing Quiet confidence, specifically valuing its smoothness, clear system, intuitive structure, and ease of understanding.

## Experience principles

### Familiar structure

Use standard product navigation and controls so the interface disappears into the task. The owner should not need to learn a novel interaction model before working on annual reporting.

### Guided without being restrictive

The annual reporting loop should identify a clear current step and next action while preserving access to transactions, documents, and company settings. Guidance belongs inside a coherent product shell rather than a single inflexible wizard.

### Calm hierarchy

Give priority to obligations, readiness, exceptions, and the next required action. Secondary metadata remains available but visually quieter. Avoid dense dashboards, decorative metrics, and repeated card grids when a list or structured workspace communicates more directly.

### Visible correctness

Validation results, assumptions, warnings, review state, and filing readiness must appear at the point of decision. Status must never rely on color alone, and errors must explain both the problem and the next action.

### Deliberate scope

The default interface serves a simple holding AS. Payroll, invoicing, VAT, and other operating-company concepts must not appear as dormant navigation or upsell clutter. Unsupported cases should be explained and escalated clearly.

## Interface implications

- A persistent, compact navigation model for annual overview, transactions, documents, and company settings.
- An annual overview organized around progress and actionable obligations rather than headline metrics.
- One consistent component vocabulary across forms, review steps, filing states, and settings.
- Norwegian-first, plain-spoken copy with necessary accounting terminology explained in context.
- Restrained accent use for primary actions, active navigation, focus, and meaningful state.
- Product-scale typography, moderate density, and limited motion used to communicate state changes.
- WCAG 2.2 AA as the accessibility baseline, including keyboard operation, visible focus, screen-reader semantics, sufficient contrast, non-color cues, and reduced-motion support.

## Explicit exclusions

- Visual imitation of Fiken.
- Generic AI-product aesthetics or ornamental interface effects.
- Cluttered all-in-one dashboards and feature bloat.
- Accounting jargon without explanation.
- Decorative motion, unusual standard controls, or navigation that hides essential context.
- A wizard-only architecture that makes other company records difficult to reach.

## Validation criteria

The direction succeeds when a representative owner can identify the current annual-reporting state, the next required action, and any blocking issue without instruction; move among the four primary areas without confusion; and understand why a filing is ready or blocked. Visual review must also confirm consistent components, readable hierarchy, restrained use of color, and no reliance on color alone for status.

## Next design task

Generate `DESIGN.md` from the current code and this approved direction. The documentation pass should distinguish existing implementation choices worth preserving from prototype patterns that conflict with Quiet confidence.
